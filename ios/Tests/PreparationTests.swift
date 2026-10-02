import Foundation

@main @MainActor
struct PreparationTests {
    static func main() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [PreparationProtocol.self]
        let api = APIClient(baseURL: URL(string: "https://test.invalid")!, session: URLSession(configuration: config))
        let session = TripSession(trip: TripSummary(id: UUID(), destination: "Tokyo", cities: ["Tokyo"],
            country: "Japan", timezone: "Asia/Tokyo", startDate: "2026-10-01", endDate: "2026-10-01", days: 1, status: "active"),
            travelerID: UUID(), planRequest: .standard)
        let checklist = ChecklistViewModel(session: session, api: api)
        await checklist.load()
        precondition(checklist.items.count == 1)
        let original = checklist.items[0]
        await checklist.toggle(original)
        precondition(checklist.items[0].completed)
        precondition(checklist.items[0].revision == 2)
        let failed = await checklist.save(original, title: "Stale edit", notes: "Keep my unsaved notes")
        precondition(!failed && checklist.errorMessage != nil)
        precondition(checklist.items[0].title == "Train tickets", "Failed save must preserve displayed tasks")
        await checklist.load()
        precondition(checklist.errorMessage == nil, "Successful reload clears the stale warning")
        let hotel = LodgingViewModel(session: session, apiClient: api)
        await hotel.load()
        precondition(hotel.selectedID == hotel.options.last?.id, "Restore the saved selection instead of the first option")
        hotel.hotelQuery = "Hotel Nikko"
        await hotel.searchHotels()
        precondition(hotel.hotelMatches.count == 1)
        await hotel.saveHotel(hotel.hotelMatches[0])
        precondition(hotel.options.first?.isBooked == true && hotel.selectedID == hotel.options.first?.id)
        precondition(hotel.hotelMatches.isEmpty)
        let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(
            BookedHotelRequest(travelerID: session.travelerID, city: "Tokyo", query: "Hotel Nikko", placeID: "ChIJ1"))) as! [String: Any]
        precondition(encoded["traveler_id"] != nil && encoded["place_id"] as? String == "ChIJ1")
        print("Checklist edits, stale-save recovery, booked hotel restoration and contracts passed")
    }
}

final class PreparationProtocol: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let path = request.url!.path
        var requestData = request.httpBody ?? Data()
        if let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 1024)
            while stream.hasBytesAvailable {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count <= 0 { break }
                requestData.append(contentsOf: buffer.prefix(count))
            }
        }
        let task = "\"id\":\"00000000-0000-0000-0000-000000000001\",\"title\":\"Train tickets\",\"notes\":\"\""
        let hotel = "\"name\":\"Hotel Nikko\",\"price_tier\":2,\"trip_start_date\":\"2026-10-01\",\"trip_end_date\":\"2026-10-01\",\"availability_note\":\"Booking not verified\""
        var status = 200
        let body: String
        if path.hasSuffix("/prepare") {
            body = "[{\(task),\"completed\":false,\"revision\":1}]"
        } else if path.contains("/checklist/") {
            if String(data: requestData, encoding: .utf8)?.contains("Stale edit") == true {
                status = 409; body = "{\"detail\":\"Refresh before editing\"}"
            } else { body = "{\(task),\"completed\":true,\"revision\":2}" }
        } else if path.hasSuffix("/lodging-options") {
            body = "[{\(hotel),\"candidate_id\":\"00000000-0000-0000-0000-000000000010\"},{\(hotel),\"candidate_id\":\"00000000-0000-0000-0000-000000000011\",\"is_selected\":true}]"
        } else if path.hasSuffix("/hotel-search") {
            body = "[{\"place_id\":\"ChIJ1\",\"name\":\"Hotel Nikko\"}]"
        } else {
            body = "{\(hotel),\"candidate_id\":\"00000000-0000-0000-0000-000000000011\",\"is_selected\":true,\"is_booked\":true}"
        }
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { }
}
