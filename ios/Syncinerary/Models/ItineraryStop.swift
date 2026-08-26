import Foundation

struct ItineraryStop: Decodable, Identifiable, Sendable {
    var id: UUID { candidateID }

    var timeRange: String {
        "\(startTime.prefix(5)) to \(endTime.prefix(5))"
    }

    var transitLabel: String {
        transitFromPrevMode ?? "travel"
    }

    let candidateID: UUID
    let name: String
    let area: String?
    let startTime: String
    let endTime: String
    let transitFromPrevMin: Int
    let transitFromPrevMode: String?

    enum CodingKeys: String, CodingKey {
        case candidateID = "candidate_id"
        case name
        case area
        case startTime = "start_time"
        case endTime = "end_time"
        case transitFromPrevMin = "transit_from_prev_min"
        case transitFromPrevMode = "transit_from_prev_mode"
    }
}
