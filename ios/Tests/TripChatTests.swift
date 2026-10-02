import Foundation

@main @MainActor struct TripChatTests {
    static func main() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [ChatProtocol.self]
        let client = APIClient(baseURL: URL(string: "https://test.invalid")!,
            session: URLSession(configuration: config), persistSession: false)
        let row = TripListRow(id: ChatProtocol.tripID, destination: "Boston", startDate: "2026-10-11",
            endDate: "2026-10-13", days: 3, status: "draft", travelerID: UUID(), memberCount: 2)
        let model = TripChatViewModel(trip: row, client: client)
        await model.load()
        precondition(model.session?.trip.id == row.id && model.messages.isEmpty)
        model.draft = "https://www.instagram.com/reel/example/"
        ChatProtocol.shouldFail = true
        await model.send()
        precondition(model.errorMessage != nil && !model.draft.isEmpty && model.messages.isEmpty)
        ChatProtocol.shouldFail = false
        let sending = Task { await model.send() }
        while !model.isSending { await Task.yield() }
        model.draft = "another thought"
        await model.send() // Double tapping cannot submit a second message in flight.
        await sending.value
        precondition(model.messages.count == 1 && model.messages[0].linkAttachmentID != nil)
        precondition(model.draft == "another thought", "Sending must not clear newer typing")
        precondition(ChatProtocol.posts == 2 && model.errorMessage == nil)
        model.draft = "final message"
        await model.send()
        precondition(model.draft.isEmpty && model.messages.count == 1, "Deduplicate server message IDs")
        print("Chat load, failed send recovery, concurrent send guard and newer draft preservation passed")
    }
}

final class ChatProtocol: URLProtocol, @unchecked Sendable {
    static let tripID = UUID(uuidString: "00000000-0000-0000-0000-000000000001")!
    nonisolated(unsafe) static var shouldFail = false
    nonisolated(unsafe) static var posts = 0
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let body: String
        var status = 200
        if request.httpMethod == "POST" {
            Self.posts += 1
            if Self.shouldFail { status = 503; body = #"{"detail":"Unavailable"}"# }
            else { body = #"{"id":"00000000-0000-0000-0000-000000000002","trip_id":"00000000-0000-0000-0000-000000000001","body":"shared post","kind":"link","link_attachment_id":"00000000-0000-0000-0000-000000000003","created_at":"2026-09-30T12:00:00Z"}"# }
        } else if request.url!.path.hasSuffix("messages") { body = "[]" }
        else { body = #"{"id":"00000000-0000-0000-0000-000000000001","destination":"Boston","cities":["Boston"],"start_date":"2026-10-11","end_date":"2026-10-13","days":3,"status":"draft"}"# }
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status,
            httpVersion: nil, headerFields: ["Content-Type":"application/json"])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { }
}
