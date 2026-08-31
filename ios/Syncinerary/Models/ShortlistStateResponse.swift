import Foundation

struct ShortlistStateResponse: Decodable, Sendable {
    let tripID: UUID
    let selectedCandidateIDs: [UUID]
    let mustGoCandidateIDs: [UUID]
    let wishlistExcludedIDs: [UUID]
    let confirmedBy: [UUID]
    let confirmedAt: String?
    let confirmationsRequired: Int
    let travelerCount: Int
    let isConfirmed: Bool

    enum CodingKeys: String, CodingKey {
        case tripID = "trip_id"
        case selectedCandidateIDs = "selected_candidate_ids"
        case mustGoCandidateIDs = "must_go_candidate_ids"
        case wishlistExcludedIDs = "wishlist_excluded_ids"
        case confirmedBy = "confirmed_by"
        case confirmedAt = "confirmed_at"
        case confirmationsRequired = "confirmations_required"
        case travelerCount = "traveler_count"
        case isConfirmed = "is_confirmed"
    }
}
