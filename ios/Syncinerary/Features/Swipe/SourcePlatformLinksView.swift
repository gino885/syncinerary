import SwiftUI

/// A short provenance line for the front of a swipe card. One original post
/// per represented platform is directly reachable; Details carries the full
/// evidence list when several posts came from the same platform.
struct SourcePlatformLinksView: View {
    let posts: [SourcePost]

    private var links: [SourcePlatformLink] {
        SourcePost.platformLinks(from: posts)
    }

    var body: some View {
        if !links.isEmpty {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline, spacing: AppTheme.spacingS) {
                    EyebrowText("Sources")
                    sourceLinks
                    postCount
                }

                VStack(alignment: .leading, spacing: AppTheme.spacingXS) {
                    EyebrowText("Sources")
                    sourceLinks
                    postCount
                }
            }
        }
    }

    @ViewBuilder
    private var sourceLinks: some View {
        ForEach(links, id: \.self) { link in
            Link(destination: link.url) {
                Label {
                    Text(link.label)
                        .underline()
                } icon: {
                    Image(systemName: "arrow.up.right")
                        .accessibilityHidden(true)
                }
                .font(AppType.mono)
                .textCase(.uppercase)
                .foregroundStyle(AppTheme.stamp)
            }
            .accessibilityLabel("\(link.label) source, opens the original post")
        }
    }

    private var postCount: some View {
        MetaLabel("\(posts.count) \(posts.count == 1 ? "post" : "posts")")
    }
}

#Preview {
    SourcePlatformLinksView(posts: [
        SourcePost(
            platform: "tiktok",
            label: "TikTok",
            url: "https://www.tiktok.com/@traveler/video/7481234567890123456",
            authorName: nil,
            highlight: nil
        ),
        SourcePost(
            platform: "instagram",
            label: "Instagram",
            url: "https://www.instagram.com/reel/Da2UDmNtLvp/",
            authorName: nil,
            highlight: nil
        ),
    ])
    .padding()
    .background(AppTheme.paper)
}
