import Foundation

@main struct ChatRoutingTests {
    static func main() {
        for status in ["draft", "setup"] {
            let session = TripSession(trip: TripSummary(id: UUID(), destination: "Boston", cities: ["Boston"],
                country: "US", timezone: "America/New_York", startDate: "2026-10-11", endDate: "2026-10-13",
                days: 3, status: status), travelerID: UUID(), planRequest: .standard)
            guard case let .chat(row) = AppRoute.primary(for: session) else {
                preconditionFailure("New groups must open in their chat")
            }
            precondition(row.id == session.trip.id && row.travelerID == session.travelerID)
            precondition(AppRoute.resume(session) == .chat(row))
            let populated = TripListRow(id: row.id, destination: row.destination, startDate: row.startDate,
                endDate: row.endDate, days: row.days, status: row.status, travelerID: row.travelerID, memberCount: 4)
            precondition(AppRoute.primary(for: session, row: populated) == .chat(populated))
            precondition(AppRoute.primary(for: session, forced: "active") == .itinerary(session))
        }
        print("Draft and setup groups open in chat; existing itinerary routing is preserved")
    }
}
