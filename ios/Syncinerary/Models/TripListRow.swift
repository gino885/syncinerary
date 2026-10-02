import Foundation

/// One row on the trips board. Carries this account's traveler id, because
/// every other call in the app is made as a traveler on one trip.
struct TripListRow: Codable, Sendable, Identifiable, Hashable {
    let id: UUID
    let destination: String
    let startDate: String
    let endDate: String
    let days: Int
    let status: String
    let travelerID: UUID
    let memberCount: Int

    enum CodingKeys: String, CodingKey {
        case id
        case destination
        case startDate = "start_date"
        case endDate = "end_date"
        case days
        case status
        case travelerID = "traveler_id"
        case memberCount = "member_count"
    }
}

extension TripListRow {
    init(session: TripSession) {
        self.init(id: session.trip.id, destination: session.trip.destination,
            startDate: session.trip.startDate, endDate: session.trip.endDate,
            days: session.trip.days, status: session.trip.status,
            travelerID: session.travelerID, memberCount: 1)
    }
}
