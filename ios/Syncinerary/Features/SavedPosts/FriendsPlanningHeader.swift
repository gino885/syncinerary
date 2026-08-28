import SwiftUI

struct FriendsPlanningHeader: View {
    var body: some View {
        VStack {
            Image(systemName: "person.3.fill")
                .font(.largeTitle)
                .foregroundStyle(.blue)
                .accessibilityHidden(true)

            Text("Bring everyone’s finds together")
                .font(.title2)
                .bold()
                .multilineTextAlignment(.center)

            Text("Paste Instagram, TikTok, or RedNote links. Add the place name only when the link does not reveal it.")
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding()
        .background(.blue.opacity(0.08))
        .clipShape(.rect(cornerRadius: AppLayout.cardCornerRadius))
    }
}

#Preview {
    FriendsPlanningHeader()
        .padding()
}
