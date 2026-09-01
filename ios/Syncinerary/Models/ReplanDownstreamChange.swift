import Foundation

struct ReplanDownstreamChange: Decodable, Identifiable, Sendable {
    var id: UUID { candidateID }

    let candidateID: UUID
    let oldTime: String
    let newTime: String

    enum CodingKeys: String, CodingKey {
        case candidateID = "candidate_id"
        case oldTime = "old_time"
        case newTime = "new_time"
    }
}
