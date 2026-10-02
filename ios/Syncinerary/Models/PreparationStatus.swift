import Foundation

struct PreparationStatus: Decodable, Sendable {
    let leaderID: UUID?
    let status: String
    let members: [PreparationMember]
    let links: [PreparationLink]
    let runStatus: String?
    let retryable: Bool
    enum CodingKeys: String, CodingKey {
        case leaderID = "leader_id"
        case runStatus = "run_status"
        case retryable
        case status, members, links
    }
}
