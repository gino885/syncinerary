import SwiftUI

struct PreferencePickerSheet: View {
    @Binding var interests: PreferenceSelection
    @Binding var dietaryExcludes: PreferenceSelection

    @Environment(\.dismiss) private var dismiss

    private let columns = [
        GridItem(.adaptive(minimum: 132), spacing: AppTheme.spacingS)
    ]

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: AppTheme.spacingXL) {
                    VStack(alignment: .leading, spacing: AppTheme.spacingM) {
                        EyebrowText("I want more of")
                        LazyVGrid(columns: columns, spacing: AppTheme.spacingS) {
                            ForEach(PreferenceCatalog.interests) { tag in
                                PreferenceTagButton(tag: tag, selection: $interests)
                            }
                        }
                    }

                    VStack(alignment: .leading, spacing: AppTheme.spacingM) {
                        EyebrowText("I don't eat")
                        LazyVGrid(columns: columns, spacing: AppTheme.spacingS) {
                            ForEach(PreferenceCatalog.dietaryExcludes) { tag in
                                PreferenceTagButton(tag: tag, selection: $dietaryExcludes)
                            }
                        }
                        Text("Known conflicts are hidden. Always confirm dietary needs with the restaurant.")
                            .font(.footnote)
                            .foregroundStyle(AppTheme.faded)
                    }
                }
                .padding(AppTheme.spacingL)
            }
            .background(AppTheme.paper)
            .navigationTitle("Preferences")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done", action: dismiss.callAsFunction)
                }
            }
        }
        .presentationDetents([.large])
    }
}

#Preview {
    @Previewable @State var interests = PreferenceSelection()
    @Previewable @State var dietary = PreferenceSelection()
    PreferencePickerSheet(interests: $interests, dietaryExcludes: $dietary)
}
