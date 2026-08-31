import SwiftUI

struct AttachedPostRow: View {
    let attachment: SourceAttachmentResponse

    var body: some View {
        Label {
            VStack(alignment: .leading) {
                Text(platformName)
                    .bold()
                Text(statusText)
                    .font(.subheadline)
                    .foregroundStyle(attachment.status == "ready" ? .green : .secondary)
            }
        } icon: {
            Image(systemName: attachment.status == "ready" ? "checkmark.circle.fill" : "questionmark.circle")
                .foregroundStyle(attachment.status == "ready" ? .green : .blue)
        }
        .accessibilityElement(children: .combine)
    }

    private var platformName: String {
        switch attachment.platform {
        case "instagram": "Instagram"
        case "tiktok": "TikTok"
        case "rednote": "RedNote"
        default: attachment.platform.capitalized
        }
    }

    private var statusText: String {
        if attachment.status == "ready" {
            "Added to your place cards"
        } else {
            "Type the place name above, then add again"
        }
    }
}
