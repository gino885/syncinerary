import SwiftUI

struct AttachedPostRow: View {
    let attachment: SourceAttachmentResponse

    private var isReady: Bool {
        attachment.status == "ready"
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: AppTheme.spacingM) {
            MetaLabel(platformName, color: AppTheme.ink)
                .frame(minWidth: 84, alignment: .leading)
            Text(isReady ? "Added to the deck" : "Add the place name, then add again")
                .font(.subheadline)
                .foregroundStyle(isReady ? AppTheme.ink : AppTheme.faded)
            Spacer()
            if isReady {
                Image(systemName: "checkmark")
                    .foregroundStyle(AppTheme.jade)
                    .accessibilityHidden(true)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var platformName: String {
        switch attachment.platform {
        case "instagram": "Instagram"
        case "tiktok": "TikTok"
        case "rednote": "RedNote"
        default: attachment.platform
        }
    }
}
