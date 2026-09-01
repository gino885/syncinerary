import Foundation

struct ReplanDownstreamChange: Decodable, Identifiable, Sendable {
    var id: UUID { nodeID }

    let nodeID: UUID
    let candidateID: UUID
    let oldTime: String
    let newTime: String

    enum CodingKeys: String, CodingKey {
        case nodeID = "node_id"
        case candidateID = "candidate_id"
        case oldTime = "old_time"
        case newTime = "new_time"
    }
}
