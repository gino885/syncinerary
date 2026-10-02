import Foundation

struct GatherRunStatus: Decodable, Sendable {
    let runID: UUID
    let status: String
    let phase: String
    let city: String?
    let completedUnits: Int
    let deckSize: Int?
    let errorCode: String?
    let retryable: Bool

    enum CodingKeys: String, CodingKey {
        case runID = "run_id"
        case status, phase, city, retryable
        case completedUnits = "completed_units"
        case deckSize = "deck_size"
        case errorCode = "error_code"
    }
}
