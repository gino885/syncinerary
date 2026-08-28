import Foundation

actor APIClient {
    static let shared = APIClient()

    private static let localBaseURL: URL = {
        guard let url = URL(string: "http://localhost:8000") else {
            fatalError("The local backend URL is invalid")
        }
        return url
    }()

    // For physical device testing, replace localhost with the Mac's LAN IP.
    private let baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(
        baseURL: URL = APIClient.localBaseURL,
        session: URLSession = .shared
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

    func vote(tripID: UUID, request: VoteRequest) async throws -> VoteResponse {
        try await post(path: "trips/\(tripID)/votes", body: request)
    }

    func plan(tripID: UUID, request: PlanRequest) async throws -> PlanResponse {
        try await post(path: "trips/\(tripID)/plan", body: request)
    }

    func itinerary(tripID: UUID) async throws -> ItineraryResponse {
        try await get(path: "trips/\(tripID)/itinerary")
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
