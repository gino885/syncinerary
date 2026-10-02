import Foundation

actor APIClient {
    static let shared = APIClient()

    private static let localBaseURL: URL = {
        // SYNC_API_BASE_URL lets a simulator run or a device point at another
        // host or port without editing code (see ios/README.md).
        let configured = ProcessInfo.processInfo.environment["SYNC_API_BASE_URL"]
            ?? UserDefaults.standard.string(forKey: "SYNC_API_BASE_URL")
            ?? Bundle.main.object(forInfoDictionaryKey: "SyncAPIBaseURL") as? String
        guard let url = URL(string: configured ?? "http://localhost:8000") else {
            fatalError("The backend URL is invalid")
        }
        return url
    }()

    // For physical device testing, replace localhost with the Mac's LAN IP.
    private let baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    /// Planning can re-solve thin days after per-day routing. Discovery uses
    /// short command/status requests with a separate 30-second request limit.
    private static let longRunningSession: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 180
        configuration.timeoutIntervalForResource = 300
        return URLSession(configuration: configuration)
    }()

    /// The bearer token, restored from the Keychain on first use so a
    /// relaunch does not sign the person out.
    private var token: String?
    private let persistSession: Bool
    private var sessionGeneration = UUID()

    init(
        baseURL: URL = APIClient.localBaseURL,
        session: URLSession = APIClient.longRunningSession,
        persistSession: Bool = true
    ) {
        self.baseURL = baseURL
        self.session = session
        self.persistSession = persistSession
        self.token = persistSession ? KeychainTokenStore.load() : nil

        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    func health() async throws -> HealthResponse {
        try await get(path: "health")
    }

    // MARK: Identity

    func signIn(email: String, password: String) async throws -> SignInResponse {
        let started = sessionGeneration
        let response: SignInResponse = try await post(
            path: "auth/session", body: SignInRequest(email: email, password: password)
        )
        guard started == sessionGeneration else { throw CancellationError() }
        token = response.token
        if persistSession { KeychainTokenStore.save(response.token) }
        return response
    }

    func authAction(_ path: String, request: EmailAuthRequest) async throws {
        let _: AuthAcknowledgement = try await post(path: "auth/\(path)", body: request)
    }

    func register(email: String, displayName: String, password: String) async throws -> SignInResponse {
        let started = sessionGeneration
        let response: SignInResponse = try await post(path: "auth/register", body:
            EmailAuthRequest(email: email, displayName: displayName, password: password))
        guard started == sessionGeneration else { throw CancellationError() }
        token = response.token
        if persistSession { KeychainTokenStore.save(response.token) }
        return response
    }

    func socialChallenge(provider: String) async throws -> SocialAuthChallenge {
        try await post(path: "auth/\(provider)/challenge", body: [String: String]())
    }

    func socialSignIn(provider: String, identity: SocialSignInRequest) async throws -> SignInResponse {
        let started = sessionGeneration
        let response: SignInResponse = try await post(path: "auth/\(provider)/session", body: identity)
        guard started == sessionGeneration else { throw CancellationError() }
        token = response.token
        if persistSession { KeychainTokenStore.save(response.token) }
        return response
    }

    func signOut() async throws {
        var request = URLRequest(url: baseURL.appending(path: "auth/session"))
        request.httpMethod = "DELETE"
        request.timeoutInterval = 30
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let (_, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) || http.statusCode == 401 else {
            throw APIError.badStatus(http.statusCode, nil)
        }
        clearSession()
    }

    func clearSession() {
        sessionGeneration = UUID()
        token = nil
        if persistSession { KeychainTokenStore.delete() }
    }

    var isSignedIn: Bool { token != nil }

    func currentAccount() async throws -> Account {
        try await get(path: "auth/me")
    }

    func myTrips() async throws -> [TripListRow] {
        try await get(path: "accounts/me/trips")
    }

    func anthropicCredential() async throws -> AnthropicCredentialStatus {
        try await get(path: "accounts/me/anthropic-key")
    }

    func saveAnthropicCredential(
        apiKey: String,
        consentToAnthropic: Bool
    ) async throws -> AnthropicCredentialStatus {
        try await put(
            path: "accounts/me/anthropic-key",
            body: AnthropicCredentialRequest(
                apiKey: apiKey,
                consentToAnthropic: consentToAnthropic
            )
        )
    }

    func removeAnthropicCredential() async throws {
        var request = URLRequest(url: baseURL.appending(path: "accounts/me/anthropic-key"))
        request.httpMethod = "DELETE"
        try await sendWithoutBody(request)
    }

    func anthropicConsent() async throws -> AnthropicConsentStatus {
        try await get(path: "accounts/me/ai-consent")
    }

    func grantAnthropicConsent() async throws -> AnthropicConsentStatus {
        try await put(
            path: "accounts/me/ai-consent",
            body: AnthropicConsentRequest(consentToAnthropic: true)
        )
    }

    func revokeAnthropicConsent() async throws {
        var request = URLRequest(url: baseURL.appending(path: "accounts/me/ai-consent"))
        request.httpMethod = "DELETE"
        try await sendWithoutBody(request)
    }

    func deleteAccount(currentPassword: String? = nil, socialIdentity: SocialSignInRequest? = nil) async throws {
        var request = URLRequest(url: baseURL.appending(path: "accounts/me/delete"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try encoder.encode(
            DeleteAccountRequest(currentPassword: currentPassword, socialIdentity: socialIdentity)
        )
        try await sendWithoutBody(request)
        clearSession()
    }

    // MARK: Invites

    func createInvite(tripID: UUID, maxUses: Int = 20) async throws -> TripInvite {
        try await post(
            path: "trips/\(tripID)/invites",
            body: InviteCreateRequest(maxUses: maxUses)
        )
    }

    func invites(tripID: UUID) async throws -> [TripInvite] {
        try await get(path: "trips/\(tripID)/invites")
    }

    func revokeInvite(tripID: UUID, code: String) async throws -> TripInvite {
        try await delete(path: "trips/\(tripID)/invites/\(code)")
    }

    /// Readable without a session, so somebody can see what they are joining
    /// before they sign in.
    func invitePreview(code: String) async throws -> InvitePreview {
        try await get(path: "invites/\(code)")
    }

    func joinTrip(code: String, request: JoinTripRequest) async throws -> JoinTripResponse {
        try await post(path: "invites/\(code)/join", body: request)
    }

    // MARK: The thread

    func messages(tripID: UUID) async throws -> [TripMessage] {
        try await get(path: "trips/\(tripID)/messages")
    }

    func namePlace(
        tripID: UUID,
        messageID: UUID,
        placeName: String
    ) async throws -> TripMessage {
        try await post(
            path: "trips/\(tripID)/messages/\(messageID)/name-place",
            body: NamePlaceRequest(placeName: placeName)
        )
    }

    func postMessage(tripID: UUID, body: String) async throws -> TripMessage {
        try await post(
            path: "trips/\(tripID)/messages",
            body: PostMessageRequest(body: body)
        )
    }

    func createTrip(_ request: TripCreateRequest) async throws -> TripCreatedResponse {
        try await post(path: "trips", body: request)
    }

    func citySuggestions(country: String, query: String) async throws -> [CitySuggestion] {
        try await get(
            path: "trips/city-suggestions",
            queryItems: [
                URLQueryItem(name: "country", value: country),
                URLQueryItem(name: "q", value: query),
            ]
        )
    }

    func startGather(tripID: UUID) async throws -> GatherRunStatus {
        try await post(path: "trips/\(tripID)/gather-runs", body: EmptyRequest())
    }

    func gatherStatus(tripID: UUID) async throws -> GatherRunStatus {
        try await get(path: "trips/\(tripID)/gather-runs/current")
    }

    func preparation(tripID: UUID) async throws -> PreparationStatus {
        try await get(path: "trips/\(tripID)/preparation")
    }

    func savePreferences(tripID: UUID, interests: [String], dietaryExcludes: [String]) async throws -> PreparationMember {
        try await put(path: "trips/\(tripID)/preferences",
                      body: MemberPreferencesRequest(interests: interests, dietaryExcludes: dietaryExcludes))
    }

    func gather(tripID: UUID) async throws -> GatherResponse {
        try await post(path: "trips/\(tripID)/gather", body: EmptyRequest())
    }

    /// The trip as the server sees it now, used to resume a saved trip at
    /// the right step.
    func trip(tripID: UUID) async throws -> TripSummary {
        try await get(path: "trips/\(tripID)")
    }

    func attachLink(
        tripID: UUID,
        request: AttachmentLinkRequest
    ) async throws -> SourceAttachmentResponse {
        try await post(path: "trips/\(tripID)/attachments/links", body: request)
    }

    func candidates(tripID: UUID, travelerID: UUID) async throws -> [CandidateCard] {
        try await get(
            path: "trips/\(tripID)/candidates",
            queryItems: [URLQueryItem(name: "traveler_id", value: travelerID.uuidString)]
        )
    }

    func candidatePhoto(tripID: UUID, candidateID: UUID) async throws -> CandidatePhoto {
        try await get(path: "trips/\(tripID)/candidates/\(candidateID)/photo")
    }

    func prepareChecklist(tripID: UUID, travelerID: UUID) async throws -> [ChecklistItem] {
        try await post(path: "trips/\(tripID)/checklist/prepare", body: ChecklistRequest(travelerID: travelerID))
    }

    func saveChecklistItem(tripID: UUID, itemID: UUID?, request: ChecklistRequest) async throws -> ChecklistItem {
        if let itemID { return try await put(path: "trips/\(tripID)/checklist/\(itemID)", body: request) }
        return try await post(path: "trips/\(tripID)/checklist", body: request)
    }

    func removeChecklistItem(tripID: UUID, travelerID: UUID, item: ChecklistItem) async throws {
        guard var parts = URLComponents(url: baseURL.appending(path: "trips/\(tripID)/checklist/\(item.id)"), resolvingAgainstBaseURL: false) else { throw APIError.invalidResponse }
        parts.queryItems = [URLQueryItem(name: "traveler_id", value: travelerID.uuidString),
                           URLQueryItem(name: "revision", value: String(item.revision))]
        guard let url = parts.url else { throw APIError.invalidResponse }
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        let _: [String: Bool] = try await send(request)
    }

    func searchHotels(tripID: UUID, travelerID: UUID, city: String, query: String) async throws -> [HotelMatch] {
        try await get(path: "trips/\(tripID)/hotel-search", queryItems: [
            URLQueryItem(name: "traveler_id", value: travelerID.uuidString),
            URLQueryItem(name: "city", value: city), URLQueryItem(name: "q", value: query)])
    }

    func saveBookedHotel(tripID: UUID, request: BookedHotelRequest) async throws -> LodgingOption {
        try await post(path: "trips/\(tripID)/booked-hotel", body: request)
    }

    func lodgingOptions(tripID: UUID) async throws -> [LodgingOption] {
        try await get(path: "trips/\(tripID)/lodging-options")
    }

    func selectLodging(
        tripID: UUID,
        request: LodgingSelectionRequest
    ) async throws -> LodgingOption {
        try await post(path: "trips/\(tripID)/lodging-selection", body: request)
    }

    func vote(tripID: UUID, request: VoteRequest) async throws -> VoteResponse {
        try await post(path: "trips/\(tripID)/votes", body: request)
    }

    func buildShortlist(tripID: UUID) async throws -> ShortlistStateResponse {
        try await post(path: "trips/\(tripID)/shortlist/build", body: EmptyRequest())
    }

    func shortlist(tripID: UUID) async throws -> ShortlistStateResponse {
        try await get(path: "trips/\(tripID)/shortlist")
    }

    func editShortlist(
        tripID: UUID,
        request: ShortlistEditRequest
    ) async throws -> ShortlistStateResponse {
        try await put(path: "trips/\(tripID)/shortlist", body: request)
    }

    func confirmShortlist(
        tripID: UUID,
        request: ShortlistConfirmRequest
    ) async throws -> ShortlistStateResponse {
        try await post(path: "trips/\(tripID)/shortlist/confirm", body: request)
    }

    func plan(tripID: UUID, request: PlanRequest) async throws -> PlanResponse {
        try await post(path: "trips/\(tripID)/plan", body: request)
    }

    static func itineraryQueryItems(travelerID: UUID) -> [URLQueryItem] {
        [URLQueryItem(name: "traveler_id", value: travelerID.uuidString)]
    }

    func itinerary(tripID: UUID, travelerID: UUID) async throws -> ItineraryResponse {
        try await get(
            path: "trips/\(tripID)/itinerary",
            queryItems: Self.itineraryQueryItems(travelerID: travelerID)
        )
    }

    func itineraryPlaces(tripID: UUID, travelerID: UUID, day: Int, query: String = "") async throws -> [ItineraryPlaceOption] {
        try await get(path: "trips/\(tripID)/itinerary/edit-places", queryItems: [
            URLQueryItem(name: "traveler_id", value: travelerID.uuidString),
            URLQueryItem(name: "day", value: String(day)), URLQueryItem(name: "q", value: query),
        ])
    }

    func selectItineraryPlace(tripID: UUID, request: SelectItineraryPlaceRequest) async throws -> ItineraryPlaceOption {
        try await post(path: "trips/\(tripID)/itinerary/edit-places", body: request)
    }

    func previewItineraryEdit(tripID: UUID, request: ManualItineraryRequest) async throws -> ReplanProposalResponse {
        try await post(path: "trips/\(tripID)/itinerary/edits", body: request)
    }

    func approveReplan(
        tripID: UUID,
        eventID: UUID,
        travelerID: UUID
    ) async throws -> ReplanProposalResponse {
        try await post(
            path: "trips/\(tripID)/replans/\(eventID)/approve",
            body: ReplanDecisionRequest(travelerID: travelerID)
        )
    }

    func rejectReplan(
        tripID: UUID,
        eventID: UUID,
        travelerID: UUID
    ) async throws -> ReplanProposalResponse {
        try await post(
            path: "trips/\(tripID)/replans/\(eventID)/reject",
            body: ReplanDecisionRequest(travelerID: travelerID)
        )
    }

    func pendingReplans(
        tripID: UUID,
        travelerID: UUID
    ) async throws -> [ReplanProposalResponse] {
        try await get(
            path: "trips/\(tripID)/replans/pending",
            queryItems: [URLQueryItem(name: "traveler_id", value: travelerID.uuidString)]
        )
    }

    static func replanWebSocketRequest(
        baseURL: URL,
        tripID: UUID,
        travelerID: UUID,
        bearerToken: String
    ) throws -> URLRequest {
        let endpoint = baseURL.appending(path: "trips/\(tripID)/replans/ws")
        guard var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidResponse
        }
        switch components.scheme {
        case "http":
            components.scheme = "ws"
        case "https":
            components.scheme = "wss"
        default:
            throw APIError.invalidResponse
        }
        components.queryItems = [
            URLQueryItem(name: "traveler_id", value: travelerID.uuidString)
        ]
        guard let url = components.url else {
            throw APIError.invalidResponse
        }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(bearerToken)", forHTTPHeaderField: "Authorization")
        return request
    }

    func nextReplanProposal(
        tripID: UUID,
        travelerID: UUID
    ) async throws -> ReplanProposalResponse {
        guard let token else { throw APIError.badStatus(401, "Sign in first") }
        let request = try Self.replanWebSocketRequest(
            baseURL: baseURL,
            tripID: tripID,
            travelerID: travelerID,
            bearerToken: token
        )
        let task = session.webSocketTask(with: request)
        task.resume()
        defer { task.cancel(with: .goingAway, reason: nil) }

        let message = try await task.receive()
        let data: Data
        switch message {
        case let .data(value):
            data = value
        case let .string(value):
            data = Data(value.utf8)
        @unknown default:
            throw APIError.invalidResponse
        }
        do {
            let envelope = try decoder.decode(ReplanEnvelope.self, from: data)
            guard envelope.type == "replan_proposed" else {
                throw APIError.invalidResponse
            }
            return envelope.proposal
        } catch let error as APIError {
            throw error
        } catch {
            throw APIError.decoding(error.localizedDescription)
        }
    }

    private func get<Response: Decodable & Sendable>(
        path: String,
        queryItems: [URLQueryItem] = []
    ) async throws -> Response {
        let endpoint = baseURL.appending(path: path)
        guard var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidResponse
        }
        components.queryItems = queryItems.isEmpty ? nil : queryItems
        guard let url = components.url else {
            throw APIError.invalidResponse
        }
        let request = URLRequest(url: url)
        return try await send(request)
    }

    private func post<Response: Decodable & Sendable, Body: Encodable & Sendable>(
        path: String,
        body: Body
    ) async throws -> Response {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try encoder.encode(body)
        return try await send(request)
    }

    private func put<Response: Decodable & Sendable, Body: Encodable & Sendable>(
        path: String,
        body: Body
    ) async throws -> Response {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try encoder.encode(body)
        return try await send(request)
    }

    private func delete<Response: Decodable & Sendable>(
        path: String
    ) async throws -> Response {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "DELETE"
        return try await send(request)
    }

    private func send<Response: Decodable & Sendable>(
        _ request: URLRequest
    ) async throws -> Response {
        var request = request
        let path = request.url?.path ?? ""
        if path.hasPrefix("/auth/") || path.hasPrefix("/accounts/me/")
            || path.contains("gather-runs") || path == "/trips"
            || path.hasSuffix("/preparation") || path.hasSuffix("/preferences") {
            request.timeoutInterval = 30
        }
        // Attached here rather than at each call site so no new endpoint can
        // forget it.
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            let serverError = try? decoder.decode(ServerErrorResponse.self, from: data)
            throw APIError.badStatus(httpResponse.statusCode, serverError?.detail)
        }
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw APIError.decoding(error.localizedDescription)
        }
    }

    private func sendWithoutBody(_ request: URLRequest) async throws {
        var request = request
        request.timeoutInterval = 30
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            let serverError = try? decoder.decode(ServerErrorResponse.self, from: data)
            throw APIError.badStatus(httpResponse.statusCode, serverError?.detail)
        }
    }
}
