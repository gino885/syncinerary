import Foundation

@main
@MainActor
enum ManualItineraryTests {
    static func main() async throws {
        let id = UUID()
        let stop = ItineraryDraftStop(candidateID: id, name: "Museum", day: 1,
                                     startMinute: 630, durationMinutes: 90, fixed: false)
        let request = ManualItineraryRequest(travelerID: UUID(), baseVersionID: UUID(),
                                            stops: [stop], adjustDays: [])
        let json = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as! [String: Any]
        let encoded = (json["stops"] as! [[String: Any]])[0]
        precondition(encoded["candidate_id"] as? String == id.uuidString)
        precondition(encoded["start_time"] as? String == "10:30")
        precondition(encoded["end_time"] as? String == "12:00")
        precondition(encoded["name"] == nil, "Names are resolved server-side")
        let trigger = try JSONDecoder().decode(ReplanTrigger.self, from: Data("\"user_request\"".utf8))
        precondition(trigger == .userRequest)
        let itinerary = try JSONDecoder().decode(ItineraryResponse.self, from: Data("""
        {"version_id":"00000000-0000-0000-0000-000000000001","version_no":1,"status":"active","days":[{"day":0,"date":"2026-10-01","stops":[
        {"candidate_id":"00000000-0000-0000-0000-000000000010","name":"Museum","start_time":"09:00:00","end_time":"10:00:00","transit_from_prev_min":0,"source_badges":[],"source_posts":[]},
        {"candidate_id":"00000000-0000-0000-0000-000000000011","name":"Market","start_time":"10:30:00","end_time":"11:30:00","transit_from_prev_min":10,"source_badges":[],"source_posts":[]}]}],"wishlist_not_placed":[]}
        """.utf8))
        let trip = TripSummary(id: UUID(), destination: "Tokyo", cities: ["Tokyo"], country: "Japan",
            timezone: "Asia/Tokyo", startDate: "2026-10-01", endDate: "2026-10-01", days: 1, status: "active")
        let session = TripSession(trip: trip, travelerID: UUID(), planRequest: .standard)
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [ManualEditFailureProtocol.self]
        let api = APIClient(baseURL: URL(string: "https://test.invalid")!, session: URLSession(configuration: config))
        let model = ManualItineraryViewModel(session: session, itinerary: itinerary, apiClient: api)
        model.move(from: IndexSet(integer: 1), to: 0)
        precondition(model.dayStops.map(\.name) == ["Market", "Museum"])
        precondition(model.dayStops[1].startMinute >= model.dayStops[0].endMinute)
        let draft = model.stops
        let failed = await model.preview()
        precondition(failed == nil && model.errorMessage != nil && !model.isSubmitting)
        precondition(model.stops == draft, "Provider failure must preserve all unsaved edits")
        model.remove(model.dayStops[0])
        precondition(model.stops.count == 1)
        precondition(itinerary.days[0].stops.count == 2, "Draft edits must not mutate the active plan")
        let fixed = ItineraryDraftStop(candidateID: UUID(), name: "Reservation", day: 0,
            startMinute: 900, durationMinutes: 60, fixed: true)
        model.add(fixed)
        model.remove(fixed)
        precondition(model.stops.contains(fixed))
        let beforeMove = model.stops
        model.move(from: IndexSet(integer: 1), to: 0)
        precondition(model.stops == beforeMove, "Reorder must not move a reservation")
        print("Manual itinerary contracts and draft lifecycle passed")
    }
}


final class ManualEditFailureProtocol: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let response = HTTPURLResponse(url: request.url!, statusCode: 503, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data("{\"detail\":\"Transit unavailable\"}".utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { }
}
