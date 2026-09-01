import Foundation

struct ReplanMove: Decodable, Identifiable, Sendable {
    var id: UUID { newNodeID }

    let candidateID: UUID
    let name: String
    let oldNodeID: UUID
    let newNodeID: UUID
    let oldDay: Int
    let newDay: Int
    let oldStartTime: String
    let newStartTime: String

    enum CodingKeys: String, CodingKey {
        case candidateID = "candidate_id"
        case name
        case oldNodeID = "old_node_id"
        case newNodeID = "new_node_id"
        case oldDay = "old_day"
        case newDay = "new_day"
        case oldStartTime = "old_start_time"
        case newStartTime = "new_start_time"
    }
}
