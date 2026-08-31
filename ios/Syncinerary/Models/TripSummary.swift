import Foundation

struct TripSummary: Codable, Hashable, Identifiable, Sendable {
    let id: UUID
    /// Display label, derived by the backend from `cities`.
    let destination: String
    let cities: [String]
    let country: String?
    let timezone: String?
    let startDate: String
    let endDate: String
    let days: Int
    let status: String

    enum CodingKeys: String, CodingKey {
        case id
        case destination
        case cities
        case country
        case timezone
        case startDate = "start_date"
        case endDate = "end_date"
        case days
        case status
    }
}
