import Foundation

final class GatherProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var requests: [URLRequest] = []
    nonisolated(unsafe) static var failure = false
    nonisolated(unsafe) static var discoveryFailed = false
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.requests.append(request)
        let trip = """
        {"trip":{"id":"00000000-0000-0000-0000-000000000001","destination":"Tokyo","cities":["Tokyo"],"country":"Japan","timezone":"Asia/Tokyo","start_date":"2026-10-01","end_date":"2026-10-03","days":3,"status":"draft"},"traveler_id":"00000000-0000-0000-0000-000000000002"}
        """
        let run = """
        {"run_id":"00000000-0000-0000-0000-000000000003","status":"\(Self.discoveryFailed ? "failed" : "completed")","phase":"deck_build","city":"Tokyo","completed_units":8,"deck_size":8,"error_code":null,"retryable":false}
        """
        let body = Self.failure ? "{\"detail\":\"Creation failed\"}" : (request.url!.path == "/trips" ? trip : run)
        let response = HTTPURLResponse(url: request.url!, statusCode: Self.failure ? 503 : 200,
                                       httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { }
}

@main
@MainActor
enum GatherLifecycleTests {
    static func main() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [GatherProtocol.self]
        let api = APIClient(baseURL: URL(string: "https://test.invalid")!,
                            session: URLSession(configuration: configuration))
        let create = TripCreateViewModel(apiClient: api)
        create.country = "Japan"
        create.creatorName = "Leader"
        create.selectedCities = [CitySuggestion(placeID: "tokyo", name: "Tokyo", subtitle: nil)]
        guard let session = await create.createTrip() else { fatalError("Trip creation failed") }
        precondition(session.trip.status == "draft")
        precondition(GatherProtocol.requests.map { $0.url!.path } == ["/trips"],
                     "Creation must never launch discovery")
        let gathering = GatheringViewModel(session: session, apiClient: api)
        let completed = await gathering.gather()
        precondition(completed && gathering.deckSize == 8)
        precondition(GatherProtocol.requests.last!.httpMethod == "GET")
        precondition(GatherProtocol.requests.last!.timeoutInterval == 30)
        GatherProtocol.discoveryFailed = true
        let failed = await gathering.gather()
        precondition(!failed && gathering.errorMessage != nil)
        precondition(!create.isShowingError, "Discovery failure must not become a creation error")
        GatherProtocol.failure = true
        let missing = await create.createTrip()
        precondition(missing == nil && create.isShowingError)
        print("iOS gather lifecycle tests passed")
    }
}
