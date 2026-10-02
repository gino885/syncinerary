import SwiftUI

struct SessionRecoveryView: View {
    @Environment(AccountStore.self) private var accounts

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("Let’s reconnect.").font(AppType.title)
                Text(accounts.errorMessage ?? String(localized: "Your saved sign-in is still on this device."))
                    .foregroundStyle(AppTheme.faded)
                Button {
                    Task { await accounts.restore() }
                } label: {
                    HStack {
                        if accounts.isWorking { ProgressView().tint(AppTheme.onAccent) }
                        Text("Try again")
                    }
                }.buttonStyle(JourneyButtonStyle()).disabled(accounts.isWorking)
            }.padding(24)
        }.background(AppTheme.canvas.ignoresSafeArea())
            .foregroundStyle(AppTheme.ink)
    }
}
