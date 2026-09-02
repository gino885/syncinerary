import SwiftUI

struct PreferenceTagButton: View {
    let tag: PreferenceTag
    @Binding var selection: PreferenceSelection

    private var isSelected: Bool {
        selection.contains(tag)
    }

    var body: some View {
        Button(action: toggle) {
            HStack(spacing: AppTheme.spacingS) {
                Text(tag.title)
                    .lineLimit(2)
                Spacer(minLength: 0)
                Image(systemName: "checkmark")
                    .opacity(isSelected ? 1 : 0)
                    .accessibilityHidden(true)
            }
            .font(.subheadline)
            .foregroundStyle(isSelected ? AppTheme.paper : AppTheme.ink)
            .padding(.horizontal, AppTheme.spacingM)
            .frame(maxWidth: .infinity, minHeight: AppLayout.minimumTapHeight)
            .background(isSelected ? AppTheme.ink : .clear, in: .rect(cornerRadius: AppTheme.cornerRadius))
            .overlay {
                RoundedRectangle(cornerRadius: AppTheme.cornerRadius)
                    .stroke(isSelected ? AppTheme.ink : AppTheme.rule)
            }
        }
        .buttonStyle(.plain)
        .accessibilityValue(isSelected ? "Selected" : "Not selected")
    }

    private func toggle() {
        selection.toggle(tag)
    }
}

#Preview {
    @Previewable @State var selection = PreferenceSelection()
    PreferenceTagButton(tag: PreferenceCatalog.interests[0], selection: $selection)
        .padding()
        .background(AppTheme.paper)
}
