import SwiftUI

/// One message. A link that became a candidate carries a jade stamp, which is
/// the only place the group sees what the agent took from their conversation.
struct MessageRow: View {
    let message: TripMessage

    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingXS) {
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

            Text(message.body)
                .font(AppType.body)
                .foregroundStyle(AppTheme.ink)
                .textSelection(.enabled)

            if message.becameACard {
                StampView(mark: .stage("In the deck", ink: AppTheme.jade), scale: 0.7)
                    .accessibilityLabel("This link is in the swipe deck")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
