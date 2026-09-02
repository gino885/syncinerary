import SwiftUI

/// Every post behind a card, so "trending" can be checked against who said so.
/// Each row opens the post outward; nothing is fetched or rendered in-app.
struct SourcePostsView: View {
    let posts: [SourcePost]

    var body: some View {
        if !posts.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text("From the posts")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.secondary)

                ForEach(posts, id: \.self) { post in
                    if let url = post.linkURL {
                        Link(destination: url) {
                            VStack(alignment: .leading, spacing: 2) {
                                Label(post.title, systemImage: "link")
                                    .font(.subheadline)
                                if let highlight = post.highlight {
                                    Text("\u{201C}\(highlight)\u{201D}")
                                        .font(.subheadline)
                                        .foregroundStyle(.secondary)
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
