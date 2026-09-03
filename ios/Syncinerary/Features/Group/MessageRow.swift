import SwiftUI

/// One message.
///
/// A link becomes a card showing the place it turned into; plain talk stays
/// plain text with no card around it. That difference is the point: a card
/// here means the app got something out of the message.
struct MessageRow: View {
    let message: TripMessage
    let onName: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingS) {
            HStack(alignment: .firstTextBaseline, spacing: AppTheme.spacingS) {
                Text(message.authorName ?? "Someone")
                    .font(AppType.rowTitle)
                    .foregroundStyle(AppTheme.ink)
                if let sentAt = message.sentAt {
                    Text(sentAt, format: .dateTime.hour().minute())
                        .font(AppType.mono)
                        .monospacedDigit()
                        .foregroundStyle(AppTheme.faded)
                }
            }

            if let words = spokenWords, !words.isEmpty {
                Text(words)
                    .font(AppType.body)
                    .foregroundStyle(AppTheme.ink)
                    .textSelection(.enabled)
            }

            if let link = message.link {
                MessageLinkCard(link: link, onName: onName)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// What the person actually said, with the bare URL removed once the card
    /// below is showing it. A URL printed next to its own unfurled card is
    /// the noise every chat product strips.
    private var spokenWords: String? {
        guard let url = message.link?.url else { return message.body }
        return message.body
            .replacingOccurrences(of: url, with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
