import SwiftUI

/// The photo, taped in. Nothing is written over it except the attribution
/// the photo provider requires; the name sits on the stub below.
struct SwipeCardHeroView: View {
    let candidate: CandidateCard
    let photo: CandidatePhoto?

    var body: some View {
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
