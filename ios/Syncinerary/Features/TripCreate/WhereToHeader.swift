import SwiftUI

/// The cover of the journal.
struct WhereToHeader: View {
    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingXS) {
            EyebrowText("New trip")
            Text("Where to?")
                .font(AppType.title)
                .foregroundStyle(AppTheme.ink)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, AppTheme.spacingS)
        .padding(.horizontal, AppTheme.spacingXS)
    }
}

#Preview {
    WhereToHeader()
        .padding()
        .background(AppTheme.paper)
}
