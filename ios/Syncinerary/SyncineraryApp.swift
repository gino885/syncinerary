import SwiftUI

@main
struct SyncineraryApp: App {
    @State private var accounts = AccountStore()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(accounts)
        }
    }
}
