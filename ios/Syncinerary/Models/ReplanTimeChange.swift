import Foundation

struct ReplanTimeChange: Decodable, Identifiable, Sendable {
    var id: UUID { newNodeID }

    let candidateID: UUID
    let name: String
    let oldNodeID: UUID
    let newNodeID: UUID
    let day: Int
    let oldStartTime: String
    let oldEndTime: String
    let newStartTime: String
    let newEndTime: String

    enum CodingKeys: String, CodingKey {
        case candidateID = "candidate_id"
        case name
        case oldNodeID = "old_node_id"
        case newNodeID = "new_node_id"
        case day
        case oldStartTime = "old_start_time"
        case oldEndTime = "old_end_time"
        case newStartTime = "new_start_time"
        case newEndTime = "new_end_time"
    }
}
