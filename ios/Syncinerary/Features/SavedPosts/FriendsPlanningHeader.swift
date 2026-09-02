import SwiftUI

struct FriendsPlanningHeader: View {
    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingXS) {
            EyebrowText("Saved posts")
            Text("Paste what the group has been sending.")
                .font(AppType.name)
                .foregroundStyle(AppTheme.ink)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, AppTheme.spacingS)
        .padding(.horizontal, AppTheme.spacingXS)
    }
}

#Preview {
    FriendsPlanningHeader()
        .padding()
        .background(AppTheme.paper)
}
