import Foundation

struct ReplanDiffStop: Decodable, Identifiable, Sendable {
    var id: UUID { nodeID }
    var timeRange: String { "\(startTime.prefix(5)) to \(endTime.prefix(5))" }

    let candidateID: UUID
    let name: String
    let nodeID: UUID
    let day: Int
    let startTime: String
    let endTime: String

    enum CodingKeys: String, CodingKey {
        case candidateID = "candidate_id"
        case name
        case nodeID = "node_id"
        case day
        case startTime = "start_time"
        case endTime = "end_time"
    }
}
