import Foundation

struct ChecklistRequest: Encodable, Sendable {
    let travelerID: UUID
    var title: String? = nil
    var notes: String? = nil
    var completed: Bool? = nil
    var revision: Int? = nil

    enum CodingKeys: String, CodingKey {
        case travelerID = "traveler_id"
        case title, notes, completed, revision
    }
}
