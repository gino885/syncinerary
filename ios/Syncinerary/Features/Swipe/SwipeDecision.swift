import Foundation

/// What a traveler did with the card on top of the deck. Carries the stamp
/// it prints and the small reaction it shows, so the deck, the charm, and the
/// buttons all agree.
enum SwipeDecision: Hashable, Sendable {
    case like
    case dislike
    case mustHave
    case likeWithNote(String)

    var voteSignal: VoteSignal {
        switch self {
        case .like: .like
        case .dislike: .dislike
        case .mustHave: .mustHave
        case .likeWithNote: .likeWithNote
        }
    }

    var noteText: String? {
        if case let .likeWithNote(note) = self {
            note
        } else {
            nil
        }
    }

    var stamp: StampMark {
        switch self {
        case .like: .liked
        case .dislike: .passed
        case .mustHave: .mustGo
        case .likeWithNote: .noted
        }
    }

    var reactionSymbol: String {
        switch self {
        case .like: "heart.fill"
        case .dislike: "hand.wave.fill"
        case .mustHave: "star.fill"
        case .likeWithNote: "note.text"
        }
    }

    /// Spoken after a decision so VoiceOver users hear what happened.
    var announcement: String {
        switch self {
        case .like: "Liked"
        case .dislike: "Passed"
        case .mustHave: "Marked as must go"
        case .likeWithNote: "Liked with a note"
        }
    }
}
