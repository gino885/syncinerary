import Foundation

struct PlanResponse: Decodable, Sendable {
    let versionID: UUID
    let versionNo: Int
    let placedStops: Int
    let narrative: String?

    enum CodingKeys: String, CodingKey {
        case versionID = "version_id"
        case versionNo = "version_no"
        case placedStops = "placed_stops"
        case narrative
    }
}
