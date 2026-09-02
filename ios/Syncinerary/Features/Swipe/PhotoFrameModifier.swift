import SwiftUI

/// Two shapes for the same photo: the deck's card takes whatever it is
/// given, the detail sheet keeps a 4:3 frame.
struct PhotoFrameModifier: ViewModifier {
    let fillsContainer: Bool

    func body(content: Content) -> some View {
        if fillsContainer {
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .clipped()
        } else {
            content
                .aspectRatio(4 / 3, contentMode: .fit)
                .frame(maxWidth: .infinity)
                .clipShape(.rect(cornerRadius: AppTheme.cornerRadius))
        }
    }
}
