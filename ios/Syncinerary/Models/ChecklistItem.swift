import Foundation

struct ChecklistItem: Codable, Identifiable, Sendable {
    let id: UUID
    var title: String
    var notes: String
    var completed: Bool
    let revision: Int
}
