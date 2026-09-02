import SwiftUI

/// Row insets for a full-width control inside a plain list: keeps the
/// screen margin without the row's default vertical padding.
enum ListRowInsets {
    static let control = EdgeInsets(
        top: AppTheme.spacingM,
        leading: AppTheme.spacingL,
        bottom: AppTheme.spacingM,
        trailing: AppTheme.spacingL
    )

    /// A stamp draws an outer rule beyond its own frame, so a row holding
    /// one needs a little more room than the screen margin.
    static let stamp = EdgeInsets(
        top: AppTheme.spacingM,
        leading: AppTheme.spacingXL,
        bottom: AppTheme.spacingM,
        trailing: AppTheme.spacingXL
    )
}
