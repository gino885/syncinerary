import Foundation

struct ItineraryDraftStop: Identifiable, Encodable, Equatable, Sendable {
    var id: UUID { candidateID }
    let candidateID: UUID
    let name: String
    var day: Int
    var startMinute: Int
    var durationMinutes: Int
    let fixed: Bool

    var endMinute: Int { startMinute + durationMinutes }
    var timeRange: String { "\(Self.clock(startMinute))–\(Self.clock(endMinute))" }
    static func clock(_ minute: Int) -> String { String(format: "%02d:%02d", minute / 60, minute % 60) }
    static func minute(_ clock: String) -> Int {
        let pieces = clock.split(separator: ":")
        return (Int(pieces.first ?? "0") ?? 0) * 60 + (Int(pieces.dropFirst().first ?? "0") ?? 0)
    }
    enum CodingKeys: String, CodingKey {
        case candidateID = "candidate_id", day, startTime = "start_time", endTime = "end_time"
    }
    func encode(to encoder: any Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(candidateID, forKey: .candidateID)
        try values.encode(day, forKey: .day)
        try values.encode(Self.clock(startMinute), forKey: .startTime)
        try values.encode(Self.clock(endMinute), forKey: .endTime)
    }
}
