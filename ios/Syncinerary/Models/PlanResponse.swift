import Foundation

struct PlanResponse: Decodable, Sendable {
    let versionID: UUID
    let versionNo: Int
    let placedStops: Int
    let narrative: String?
}
