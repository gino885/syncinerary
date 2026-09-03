import SwiftUI

/// A pasted post, unfurled.
///
/// A card here has to earn itself, because "rounded card with an image and two
/// lines" is the most templated component there is. It earns it by carrying
/// what a line of text cannot: the place the post became, and whether the app
/// could read it. No shadow, no tint, no accent rail. Square except the photo,
/// which uses the radius photos already use everywhere else.
struct MessageLinkCard: View {
    let link: MessageLink
    let onName: (String) -> Void

    @State private var draftName = ""
    @FocusState private var naming: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingS) {
            if link.isInTheDeck {
                resolved
            } else if link.needsPlaceName {
                repair
            } else {
                pending
            }
        }
        .padding(AppTheme.spacingM)
        .overlay {
            Rectangle()
                .strokeBorder(AppTheme.rule, lineWidth: AppTheme.hairlineWidth)
        }
    }

    private var resolved: some View {
        HStack(alignment: .top, spacing: AppTheme.spacingM) {
            if let photo = link.photoURL, let url = URL(string: photo) {
                AsyncImage(url: url) { image in
                    image.resizable().aspectRatio(contentMode: .fill)
                } placeholder: {
                    Rectangle().fill(AppTheme.rule.opacity(0.4))
                }
                .frame(width: 56, height: 56)
                .clipShape(RoundedRectangle(cornerRadius: AppTheme.cornerRadius))
            }

            VStack(alignment: .leading, spacing: AppTheme.spacingXS) {
                Text(link.placeName ?? "")
                    .font(AppType.rowTitle)
                    .foregroundStyle(AppTheme.ink)
                Text(link.platformLabel)
                    .font(AppType.mono)
                    .foregroundStyle(AppTheme.faded)
                StampView(mark: .stage("In the deck", ink: AppTheme.jade), scale: 0.6)
            }
            Spacer(minLength: 0)
        }
    }

    /// The same shape with a field where the photo was, so the two states read
    /// as one component at two points in its life rather than two designs.
    private var repair: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingS) {
            Text("\(link.platformLabel) won't open to us")
                .font(AppType.rowTitle)
                .foregroundStyle(AppTheme.ink)

            HStack(spacing: AppTheme.spacingS) {
                TextField("What place is it?", text: $draftName)
                    .font(AppType.body)
                    .foregroundStyle(AppTheme.ink)
                    .focused($naming)
                    .submitLabel(.done)
                    .onSubmit(submit)
                Button("Add", action: submit)
                    .font(AppType.rowTitle)
                    .foregroundStyle(canSubmit ? AppTheme.ink : AppTheme.faded)
                    .disabled(!canSubmit)
            }
            Rectangle()
                .fill(naming ? AppTheme.ink : AppTheme.rule)
                .frame(height: AppTheme.hairlineWidth)
        }
    }

    private var pending: some View {
        Text("Reading the \(link.platformLabel) post")
            .font(AppType.mono)
            .foregroundStyle(AppTheme.faded)
    }

    private var canSubmit: Bool {
        !draftName.trimmingCharacters(in: .whitespaces).isEmpty
    }

    private func submit() {
        let name = draftName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        onName(name)
        draftName = ""
        naming = false
    }
}
