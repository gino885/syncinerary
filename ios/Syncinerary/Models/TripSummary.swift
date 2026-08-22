import Foundation

struct TripSummary: Codable, Hashable, Identifiable, Sendable {
    let id: UUID
    let destination: String
    let startDate: String
    let endDate: String
    let days: Int
    let status: String
}
