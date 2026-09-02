import Foundation

actor APIClient {
    static let shared = APIClient()

    private static let localBaseURL: URL = {
        // SYNC_API_BASE_URL lets a simulator run or a device point at another
        // host or port without editing code (see ios/README.md).
        let configured = ProcessInfo.processInfo.environment["SYNC_API_BASE_URL"]
            ?? UserDefaults.standard.string(forKey: "SYNC_API_BASE_URL")
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

    /// Gather now runs a destination search, three social searches, entity
    /// extraction, and geocoding before it returns, which can take well over
    /// the 60 second default. Planning re-solves thin days on top of the
    /// per-day routing. Both need a longer ceiling than `URLSession.shared`.
    private static let longRunningSession: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 180
        configuration.timeoutIntervalForResource = 300
        return URLSession(configuration: configuration)
    }()

    init(
        baseURL: URL = APIClient.localBaseURL,
        session: URLSession = APIClient.longRunningSession
    ) {
        self.baseURL = baseURL
        self.session = session

        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    func health() async throws -> HealthResponse {
        try await get(path: "health")
    }

    func createTrip(_ request: TripCreateRequest) async throws -> TripCreatedResponse {
        try await post(path: "trips", body: request)
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

    static func replanWebSocketURL(
        baseURL: URL,
        tripID: UUID,
        travelerID: UUID
    ) throws -> URL {
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
        return url
    }

    func nextReplanProposal(
        tripID: UUID,
        travelerID: UUID
    ) async throws -> ReplanProposalResponse {
        let url = try Self.replanWebSocketURL(
            baseURL: baseURL,
            tripID: tripID,
            travelerID: travelerID
        )
        let task = session.webSocketTask(with: url)
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

    private func send<Response: Decodable & Sendable>(
        _ request: URLRequest
    ) async throws -> Response {
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
}
