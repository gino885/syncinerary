import Foundation

struct ReplanProposalResponse: Decodable, Identifiable, Sendable {
    var id: UUID { eventID }

    let eventID: UUID
    let tripID: UUID
    let triggerType: ReplanTrigger
    let status: ReplanStatus
    let currentVersionID: UUID
    let proposedVersionID: UUID
    let trace: ReplanTrace
    let diff: ReplanDiff

    enum CodingKeys: String, CodingKey {
        case eventID = "event_id"
        case tripID = "trip_id"
        case triggerType = "trigger_type"
        case status
        case currentVersionID = "current_version_id"
        case proposedVersionID = "proposed_version_id"
        case trace
        case diff
    }
}
