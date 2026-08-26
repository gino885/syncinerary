import Foundation

struct TripSummary: Codable, Hashable, Identifiable, Sendable {
    let id: UUID
    let destination: String
    let startDate: String
    let endDate: String
    let days: Int
    let status: String

    enum CodingKeys: String, CodingKey {
        case id
        case destination
        case startDate = "start_date"
        case endDate = "end_date"
        case days
        case status
    }
}
