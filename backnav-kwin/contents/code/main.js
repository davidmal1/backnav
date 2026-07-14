//
// BackNav KWin Event Producer
// Version 0.1
//

function emitEvent(window)
{
    if (!window)
        return;

    const event = {
        version: 1,
        timestamp: Date.now(),

        window: {
            id: window.internalId,
            app: window.resourceClass,
            title: window.caption
        },

        flags: {
            transient: window.transient,
            modal: window.modal,
            normal: window.normalWindow
        }
    };

    console.log(JSON.stringify(event));
}

// Initial state
emitEvent(workspace.activeWindow);

// Future activations
workspace.windowActivated.connect(function(window) {
    emitEvent(window);
});
