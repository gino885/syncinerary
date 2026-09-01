import Foundation

struct ReplanAffectedNode: Decodable, Identifiable, Sendable {
    var id: UUID { nodeID }

    let nodeID: UUID
    let candidateID: UUID
    let classification: String

    enum CodingKeys: String, CodingKey {
        case nodeID = "node_id"
        case candidateID = "candidate_id"
        case classification
    }
}
