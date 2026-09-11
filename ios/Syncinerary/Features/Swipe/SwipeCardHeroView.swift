import SwiftUI

/// The photo, taped in. Nothing is written over it except the attribution
/// the photo provider requires; the name sits on the stub below.
struct SwipeCardHeroView: View {
    let candidate: CandidateCard
    let photo: CandidatePhoto?
    var onPlaybackChange: (Bool) -> Void = { _ in }

    @State private var showingReel = false

    private var reelURL: URL? {
        candidate.sourcePosts.compactMap(\.instagramReelURL).first
    }

    var body: some View {
        if showingReel, let reelURL {
            VStack(spacing: 0) {
                InstagramReelView(url: reelURL)
                HStack {
                    Link("Open in Instagram", destination: reelURL)
                    Spacer()
                    Button("Show photo") {
                        showingReel = false
                        onPlaybackChange(false)
                    }
                }
                .font(.caption)
                .padding(.horizontal)
                .frame(minHeight: AppLayout.minimumTapHeight)
            }
            .frame(minHeight: 300)
        } else {
            photoContent.overlay(alignment: .bottomTrailing) {
                if reelURL != nil {
                    Button("Watch Reel", systemImage: "play.circle.fill") {
                        showingReel = true
                        onPlaybackChange(true)
                    }
                        .buttonStyle(.plain)
                        .foregroundStyle(AppTheme.ink)
                        .padding(.horizontal, AppTheme.spacingM)
                        .frame(minHeight: AppLayout.minimumTapHeight)
                        .background(AppTheme.paper, in: .capsule)
                        .padding()
                }
            }
        }
    }

    private var photoContent: some View {
        CandidatePhotoView(photo: photo, placeName: candidate.nameCanonical, fillsContainer: true)
            .overlay(alignment: .top) {
                AppTheme.photoScrim
                    .frame(height: 68)
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
            }
            .overlay(alignment: .bottom) {
                Rectangle()
                    .fill(AppTheme.rule)
                    .frame(height: AppTheme.hairlineWidth)
            }
    }
}
