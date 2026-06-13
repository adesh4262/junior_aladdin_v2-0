/**
 * Junior Aladdin — Operator Terminal
 * component_manager.js — Component lifecycle manager
 *
 * Manages registration, mounting, unmounting, and updating of
 * UI components. Tracks active mounts to prevent subscription leaks.
 *
 * Reference: ROADMAP_SIDE_B Step 8.12
 */

const ComponentManager = {
    _components: new Map(),
    _mounted: new Map(),

    /**
     * Register a component.
     * @param {string} name
     * @param {object} component - { mount(container), unmount(), update(state) }
     */
    register(name, component) {
        this._components.set(name, component);
    },

    /**
     * Mount a component into a container.
     * Auto-unmounts any previously mounted instance to prevent duplicate subscriptions.
     * @param {string} name
     * @param {HTMLElement} container
     */
    mount(name, container) {
        const component = this._components.get(name);
        if (!component) {
            console.warn(`[ComponentManager] Unknown component: ${name}`);
            return;
        }
        // Unmount previous instance first (prevents subscription leaks on re-navigation)
        if (this._mounted.has(name)) {
            const prev = this._mounted.get(name);
            if (prev !== container && component.unmount) {
                component.unmount();
            }
        }
        this._mounted.set(name, container);
        if (component.mount) {
            container.innerHTML = '';
            component.mount(container);
        }
    },

    /**
     * Unmount a component.
     * @param {string} name
     */
    unmount(name) {
        const component = this._components.get(name);
        if (component && component.unmount) {
            component.unmount();
        }
        this._mounted.delete(name);
    },

    /**
     * Unmount all mounted components.
     */
    unmountAll() {
        for (const name of this._mounted.keys()) {
            this.unmount(name);
        }
    },

    /**
     * Update a component with new state.
     * @param {string} name
     * @param {object} state
     */
    update(name, state) {
        const component = this._components.get(name);
        if (component && component.update) {
            component.update(state);
        }
    }
};
