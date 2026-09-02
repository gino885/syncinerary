import SwiftUI

/// Every post behind a card, so "trending" can be checked against who said
/// so. Each opens the post outward; nothing is fetched or rendered here.
struct SourcePostsView: View {
    let posts: [SourcePost]

    var body: some View {
        if !posts.isEmpty {
            VStack(alignment: .leading, spacing: AppTheme.spacingS) {
                EyebrowText("Posts behind this")

                ForEach(posts, id: \.self) { post in
                    if let url = post.linkURL {
                        Link(destination: url) {
                            VStack(alignment: .leading, spacing: 2) {
                                HStack(spacing: AppTheme.spacingXS) {
                                    Text(post.title)
                                        .underline()
                                    Image(systemName: "arrow.up.right")
                                        .accessibilityHidden(true)
                                }
                                .font(AppType.mono)
                                .textCase(.uppercase)
                                .foregroundStyle(AppTheme.stamp)
                                if let highlight = post.highlight {
                                    Text("\u{201C}\(highlight)\u{201D}")
                                        .font(.subheadline)
                                        .italic()
                                        .foregroundStyle(AppTheme.faded)
                                        .multilineTextAlignment(.leading)
                                }
                            }
                        }
                        .accessibilityLabel("\(post.title), opens the post")
                    }
                }
            }
        }
    }
}
