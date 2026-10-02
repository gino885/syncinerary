import Foundation

struct PreparationMember: Decodable, Sendable, Identifiable {
    let id: UUID
    let name: String
    let preferencesComplete: Bool
    let interests: [String]?
    let dietaryExcludes: [String]?
    enum CodingKeys: String, CodingKey {
        case id, name, interests
        case preferencesComplete = "preferences_complete"
        case dietaryExcludes = "dietary_excludes"
    }
}
