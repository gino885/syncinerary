import Foundation

struct MemberPreferencesRequest: Encodable, Sendable {
    let interests: [String]
    let dietaryExcludes: [String]
    enum CodingKeys: String, CodingKey {
        case interests
        case dietaryExcludes = "dietary_excludes"
    }
}
