enum VoteSignal: String, Encodable, Sendable {
    case like
    case dislike
    case likeWithNote = "like_with_note"
    case mustHave = "must_have"
}
