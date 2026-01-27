// Инициализация Telegram Web App
const tg = window.Telegram?.WebApp || {};
const isTestMode = !tg.initDataUnsafe?.user?.id; // Тестовый режим если нет данных от Telegram

// Инициализируем только если запущено в Telegram
if (tg.expand) {
    tg.expand();
    tg.ready();
}

// API Base URL
const API_URL = window.location.origin + '/api';

// Получаем данные пользователя из Telegram или используем тестовые
const userId = tg.initDataUnsafe?.user?.id || 123456789; // Тестовый ID для разработки
const userName = tg.initDataUnsafe?.user?.first_name || 'Тестовый пользователь';

// Получаем initData для авторизации запросов
const initData = tg.initData || '';

// Функция для создания заголовков с авторизацией
function getAuthHeaders() {
    const headers = {
        'Content-Type': 'application/json'
    };
    if (initData) {
        headers['X-Telegram-Init-Data'] = initData;
    }
    return headers;
}

// Глобальные переменные
let currentGame = null;
let currentSubcategory = null;
let userProfile = null;
let allProducts = [];
let currentGameProducts = [];
let currentDisplayedProducts = []; // Товары отображаемые в общем списке (без акций)
let currentCategoryProducts = []; // Товары текущей категории
let currentProduct = null;
let bannerInterval = null;
let currentBannerIndex = 0;
let currentViewMode = 'grid'; // 'grid' или 'list'

// Lazy Loading Observer для изображений
const lazyImageObserver = new IntersectionObserver((entries, observer) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            const img = entry.target;
            if (img.dataset.src) {
                img.src = img.dataset.src;
                img.classList.add('loaded');
                observer.unobserve(img);
            }
        }
    });
}, {
    rootMargin: '50px 0px', // Начинаем загрузку за 50px до появления
    threshold: 0.01
});

// Функция для активации lazy loading на новых изображениях
function initLazyImages(container = document) {
    const lazyImages = container.querySelectorAll('img.lazy-image:not(.loaded)');
    lazyImages.forEach(img => {
        lazyImageObserver.observe(img);
    });
}

// Элементы DOM
const elements = {
    mainPage: document.getElementById('mainPage'),
    catalogPage: document.getElementById('catalogPage'),
    categoryPage: document.getElementById('categoryPage'),
    profilePage: document.getElementById('profilePage'),
    searchOverlay: document.getElementById('searchOverlay'),
    searchInput: document.getElementById('searchInput'),
    searchResults: document.getElementById('searchResults'),
    productsGrid: document.getElementById('productsGrid'),
    catalogTitle: document.getElementById('catalogTitle'),
    categoriesSection: document.getElementById('categoriesSection'),
    categoriesGrid: document.getElementById('categoriesGrid'),
    productsSection: document.getElementById('productsSection'),
    productCount: document.getElementById('productCount'),
    toastContainer: document.getElementById('toastContainer'),

    // Category page elements
    categoryTitle: document.getElementById('categoryTitle'),
    categoryProductCount: document.getElementById('categoryProductCount'),
    categoryProductsGrid: document.getElementById('categoryProductsGrid'),

    // Purchase modal elements
    purchaseModal: document.getElementById('purchaseModal'),
    purchaseProductName: document.getElementById('purchaseProductName'),
    purchasePrice: document.getElementById('purchasePrice'),
    purchasePrice2: document.getElementById('purchasePrice2'),
    purchaseDescription: document.getElementById('purchaseDescription'),
    supercellIdTextarea: document.getElementById('supercellIdTextarea'),
    charCount: document.getElementById('charCount'),
    purchaseClose: document.getElementById('purchaseClose'),
    purchaseCancel: document.getElementById('purchaseCancel'),
    purchaseCancel2: document.getElementById('purchaseCancel2'),
    purchaseContinue: document.getElementById('purchaseContinue'),
    purchaseBack: document.getElementById('purchaseBack'),
    priceToggle: document.getElementById('priceToggle'),
    priceToggle2: document.getElementById('priceToggle2'),
    priceDetails: document.getElementById('priceDetails'),
    priceDetails2: document.getElementById('priceDetails2'),
    purchaseStep1: document.getElementById('purchaseStep1'),
    purchaseStep2: document.getElementById('purchaseStep2'),
    userSupercellId: document.getElementById('userSupercellId'),
    btnEditInfo: document.getElementById('btnEditInfo'),
    paymentSbp: document.getElementById('paymentSbp'),

    // Success modal elements
    successModal: document.getElementById('successModal'),
    successOrderCode: document.getElementById('successOrderCode'),
    successProductName: document.getElementById('successProductName'),
    successPrice: document.getElementById('successPrice'),
    successSupercellId: document.getElementById('successSupercellId'),
    successCloseBtn: document.getElementById('successCloseBtn'),

    // Banner elements
    bannerSlides: document.getElementById('bannerSlides'),
    bannerDots: document.getElementById('bannerDots'),

    // Profile elements
    userUID: document.getElementById('userUID'),
    userOrders: document.getElementById('userOrders'),

    // Breadcrumb elements
    breadcrumbs: document.getElementById('breadcrumbs'),
    breadcrumbBack: document.getElementById('breadcrumbBack'),
    breadcrumbHome: document.getElementById('breadcrumbHome'),
    breadcrumbGame: document.getElementById('breadcrumbGame'),
    breadcrumbCategory: document.getElementById('breadcrumbCategory'),
    breadcrumbCategorySeparator: document.getElementById('breadcrumbCategorySeparator'),

    // View toggle elements
    viewList: document.getElementById('viewList'),
    viewGrid: document.getElementById('viewGrid'),
};

// ===== TOAST УВЕДОМЛЕНИЯ =====
function showToast(message, type = 'info') {
    const icons = {
        success: '✓',
        error: '✗',
        info: 'ℹ'
    };

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type]}</span>
        <span class="toast-message">${message}</span>
    `;

    elements.toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('hide');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ===== RIPPLE ЭФФЕКТ =====
function createRipple(event) {
    const element = event.currentTarget;
    const circle = document.createElement('span');
    const diameter = Math.max(element.clientWidth, element.clientHeight);
    const radius = diameter / 2;

    const rect = element.getBoundingClientRect();
    circle.style.width = circle.style.height = `${diameter}px`;
    circle.style.left = `${event.clientX - rect.left - radius}px`;
    circle.style.top = `${event.clientY - rect.top - radius}px`;
    circle.classList.add('ripple-effect');

    const existingRipple = element.querySelector('.ripple-effect');
    if (existingRipple) {
        existingRipple.remove();
    }

    element.appendChild(circle);
}

// ===== SKELETON LOADING =====
function showSkeletonLoading(gridElement, count = 4) {
    let skeletons = '';
    for (let i = 0; i < count; i++) {
        skeletons += `
            <div class="skeleton-card">
                <div class="skeleton-image skeleton"></div>
                <div class="skeleton-text skeleton"></div>
                <div class="skeleton-text skeleton short"></div>
                <div class="skeleton-price skeleton"></div>
            </div>
        `;
    }
    gridElement.innerHTML = skeletons;
}

// ===== BANNER СЛАЙДЕР =====
function initBannerSlider() {
    const slides = document.querySelectorAll('.banner-slide');
    const dots = document.querySelectorAll('.banner-dot');

    if (slides.length === 0) return;

    bannerInterval = setInterval(() => {
        currentBannerIndex = (currentBannerIndex + 1) % slides.length;
        updateBannerPosition();
    }, 5000);

    dots.forEach(dot => {
        dot.addEventListener('click', () => {
            currentBannerIndex = parseInt(dot.dataset.index);
            updateBannerPosition();
            resetBannerInterval();
        });
    });

    document.querySelectorAll('.banner-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const game = btn.dataset.game;
            if (game) {
                openCatalog(game);
            }
        });
    });

    let touchStartX = 0;
    let touchEndX = 0;

    elements.bannerSlides?.addEventListener('touchstart', (e) => {
        touchStartX = e.changedTouches[0].screenX;
    }, { passive: true });

    elements.bannerSlides?.addEventListener('touchend', (e) => {
        touchEndX = e.changedTouches[0].screenX;
        handleBannerSwipe();
    }, { passive: true });

    function handleBannerSwipe() {
        const swipeThreshold = 50;
        const diff = touchStartX - touchEndX;

        if (Math.abs(diff) > swipeThreshold) {
            if (diff > 0) {
                currentBannerIndex = (currentBannerIndex + 1) % slides.length;
            } else {
                currentBannerIndex = (currentBannerIndex - 1 + slides.length) % slides.length;
            }
            updateBannerPosition();
            resetBannerInterval();
        }
    }
}

function updateBannerPosition() {
    if (elements.bannerSlides) {
        elements.bannerSlides.style.transform = `translateX(-${currentBannerIndex * 100}%)`;
    }

    document.querySelectorAll('.banner-dot').forEach((dot, index) => {
        dot.classList.toggle('active', index === currentBannerIndex);
    });
}

function resetBannerInterval() {
    clearInterval(bannerInterval);
    bannerInterval = setInterval(() => {
        currentBannerIndex = (currentBannerIndex + 1) % document.querySelectorAll('.banner-slide').length;
        updateBannerPosition();
    }, 5000);
}

// ===== МОДАЛЬНОЕ ОКНО ПОКУПКИ =====
let currentSupercellId = '';

function openProductModal(product) {
    currentProduct = product;
    currentSupercellId = '';

    elements.purchaseProductName.textContent = product.name;
    elements.purchasePrice.textContent = `${formatPrice(product.price)}₽`;
    if (elements.purchasePrice2) {
        elements.purchasePrice2.textContent = `${formatPrice(product.price)}₽`;
    }
    if (elements.purchaseDescription) {
        elements.purchaseDescription.textContent = product.description || 'Нет описания';
    }

    // Очищаем форму
    elements.supercellIdTextarea.value = '';
    elements.charCount.textContent = '0/200';
    elements.purchaseContinue.disabled = true;

    // Показываем первый шаг
    showPurchaseStep(1);

    elements.purchaseModal.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeProductModal() {
    elements.purchaseModal.classList.remove('active');
    document.body.style.overflow = '';
    currentProduct = null;
    currentSupercellId = '';
    showPurchaseStep(1);
}

function showPurchaseStep(step) {
    if (step === 1) {
        elements.purchaseStep1.style.display = 'block';
        elements.purchaseStep2.style.display = 'none';
    } else if (step === 2) {
        elements.purchaseStep1.style.display = 'none';
        elements.purchaseStep2.style.display = 'block';
    }
}

function goToPaymentStep() {
    // Получаем введенные данные
    currentSupercellId = elements.supercellIdTextarea.value.trim();

    if (!currentSupercellId) {
        showToast('Введите ваш Supercell ID', 'error');
        return;
    }

    // Обновляем отображение информации пользователя
    if (elements.userSupercellId) {
        elements.userSupercellId.textContent = currentSupercellId;
    }

    // Переключаемся на второй шаг
    showPurchaseStep(2);
}

function goBackToInfoStep() {
    showPurchaseStep(1);
}

async function completeOrder() {
    if (!userId || !currentProduct || !currentSupercellId) {
        showToast('Ошибка: недостаточно данных', 'error');
        return;
    }

    // Проверяем, что запущено из Telegram
    if (!initData) {
        showToast('Ошибка: приложение должно быть запущено из Telegram', 'error');
        return;
    }

    console.log('Starting purchase...', {userId, productId: currentProduct.id, supercellId: currentSupercellId});

    try {
        const response = await fetch(`${API_URL}/purchase`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                user_id: userId,
                product_id: currentProduct.id,
                supercell_id: currentSupercellId
            })
        });

        console.log('Response status:', response.status);

        const result = await response.json();
        console.log('Response data:', result);

        // Проверяем HTTP статус
        if (!response.ok) {
            // Ошибка от сервера (401, 403, etc)
            const errorMsg = result.detail || result.message || 'Ошибка сервера';
            console.log('Server error:', errorMsg);
            showToast(errorMsg, 'error');
            return;
        }

        if (result.success) {
            console.log('Purchase successful, showing success modal');

            // Сохраняем данные ДО закрытия модала (closeProductModal очищает currentProduct)
            const productName = currentProduct.name;
            const productPrice = currentProduct.price;
            const scId = currentSupercellId;

            // Закрываем модальное окно покупки
            closeProductModal();

            // Показываем success модальное окно
            showSuccessModal(result.pickup_code, productName, productPrice, scId);

            // Обновляем профиль в фоне (не блокируем показ success)
            loadUserProfile().catch(err => console.error('Error updating profile:', err));
        } else {
            console.log('Purchase failed:', result.message);
            showToast(result.message || 'Ошибка при оформлении заказа', 'error');
        }
    } catch (error) {
        console.error('Error completing order:', error);
        showToast('Ошибка при оформлении заказа', 'error');
    }
}

function showSuccessModal(orderCode, productName, price, supercellId) {
    console.log('showSuccessModal called with:', {orderCode, productName, price, supercellId});

    if (!elements.successModal) {
        console.error('successModal element not found!');
        showToast('Заказ оформлен! Код: ' + orderCode, 'success');
        return;
    }

    // Заполняем данные
    if (elements.successOrderCode) elements.successOrderCode.textContent = `#${orderCode}`;
    if (elements.successProductName) elements.successProductName.textContent = productName;
    if (elements.successPrice) elements.successPrice.textContent = `${formatPrice(price)}₽`;
    if (elements.successSupercellId) elements.successSupercellId.textContent = supercellId;

    // Показываем модал
    elements.successModal.classList.add('active');
    document.body.style.overflow = 'hidden';

    console.log('Success modal should be visible now, classList:', elements.successModal.classList.toString());
}

function closeSuccessModal() {
    elements.successModal.classList.remove('active');
    document.body.style.overflow = '';

    // Возвращаемся на главную
    goHome();
}

function updateCharCount() {
    const count = elements.supercellIdTextarea.value.length;
    elements.charCount.textContent = `${count}/200`;

    // Активируем кнопку если есть текст
    const hasInput = elements.supercellIdTextarea.value.trim().length > 0;
    elements.purchaseContinue.disabled = !hasInput;
}

function togglePriceDetails() {
    if (!elements.priceToggle || !elements.priceDetails) {
        console.error('priceToggle elements not found');
        return;
    }
    elements.priceToggle.classList.toggle('collapsed');
    const isCollapsed = elements.priceToggle.classList.contains('collapsed');
    elements.priceDetails.style.display = isCollapsed ? 'none' : 'block';
    console.log('Toggle 1:', isCollapsed ? 'closed' : 'opened');
}

function togglePriceDetails2() {
    if (!elements.priceToggle2 || !elements.priceDetails2) {
        console.error('priceToggle2 elements not found');
        return;
    }
    elements.priceToggle2.classList.toggle('collapsed');
    const isCollapsed = elements.priceToggle2.classList.contains('collapsed');
    elements.priceDetails2.style.display = isCollapsed ? 'none' : 'block';
    console.log('Toggle 2:', isCollapsed ? 'closed' : 'opened');
}

function getCategoryName(subcategory) {
    const names = {
        // Общие (товары для общего списка)
        'all': 'Общее',
        'akcii': 'Акции',
        'gems': 'Гемы',
        // Clash Royale
        'geroi': 'Герои',
        'evolutions': 'Эволюции',
        'emoji': 'Эмодзи',
        'etapnye': 'Этапные',
        'karty': 'Карты',
        // Clash of Clans
        'oformlenie': 'Оформление'
    };
    return names[subcategory] || subcategory;
}

// Инициализация
async function init() {
    setupEventListeners();
    initBannerSlider();
    initRippleEffects();
    await loadUserProfile();
    await loadAllProducts();

    setTimeout(() => {
        showToast('Добро пожаловать в магазин!', 'success');
    }, 1000);
}

function initRippleEffects() {
    document.querySelectorAll('.ripple').forEach(element => {
        element.addEventListener('click', createRipple);
    });
}

// Настройка обработчиков событий
function setupEventListeners() {
    // Главная
    document.getElementById('homeBtn').addEventListener('click', goHome);

    // Поиск
    document.getElementById('searchBtn').addEventListener('click', openSearch);
    document.getElementById('closeSearch').addEventListener('click', closeSearch);
    elements.searchInput.addEventListener('input', handleSearch);

    // Профиль
    document.getElementById('profileBtn').addEventListener('click', openProfile);
    document.getElementById('backToMainFromProfile').addEventListener('click', closeProfile);

    // Карточки игр
    document.querySelectorAll('.game-card').forEach(card => {
        card.addEventListener('click', () => {
            const game = card.dataset.game;
            if (game) {
                openCatalog(game);
            }
        });
    });

    // Кнопка назад из каталога (старая, если есть)
    document.getElementById('backToMain')?.addEventListener('click', closeCatalog);

    // Кнопка назад из категории
    document.getElementById('backToCatalog')?.addEventListener('click', closeCategoryPage);

    // Хлебные крошки каталога
    elements.breadcrumbBack?.addEventListener('click', handleBreadcrumbBack);
    elements.breadcrumbHome?.addEventListener('click', goHome);
    elements.breadcrumbGame?.addEventListener('click', () => {
        if (currentSubcategory) {
            closeCategoryPage();
        }
    });

    // Хлебные крошки страницы категории
    document.getElementById('categoryBreadcrumbBack')?.addEventListener('click', closeCategoryPage);
    document.getElementById('categoryBreadcrumbHome')?.addEventListener('click', goHome);
    document.getElementById('categoryBreadcrumbGame')?.addEventListener('click', closeCategoryPage);

    // Переключатель вида
    elements.viewList?.addEventListener('click', () => setViewMode('list'));
    elements.viewGrid?.addEventListener('click', () => setViewMode('grid'));

    // Модальное окно покупки
    elements.purchaseClose?.addEventListener('click', closeProductModal);
    elements.purchaseCancel?.addEventListener('click', closeProductModal);
    elements.purchaseCancel2?.addEventListener('click', closeProductModal);
    elements.purchaseModal?.addEventListener('click', (e) => {
        if (e.target === elements.purchaseModal) {
            closeProductModal();
        }
    });

    // Форма покупки
    elements.supercellIdTextarea?.addEventListener('input', updateCharCount);
    elements.priceToggle?.addEventListener('click', togglePriceDetails);
    elements.priceToggle2?.addEventListener('click', togglePriceDetails2);

    // Кнопка "Продолжить" - переход к выбору оплаты
    elements.purchaseContinue?.addEventListener('click', () => {
        if (currentProduct) {
            goToPaymentStep();
        }
    });

    // Кнопка "Назад" - вернуться к вводу информации
    elements.purchaseBack?.addEventListener('click', goBackToInfoStep);

    // Кнопка "Изменить" - вернуться к редактированию информации
    elements.btnEditInfo?.addEventListener('click', goBackToInfoStep);

    // Кнопка оплаты СБП - завершить заказ
    elements.paymentSbp?.addEventListener('click', completeOrder);

    // Закрытие success модального окна
    elements.successCloseBtn?.addEventListener('click', closeSuccessModal);
    document.getElementById('successCloseX')?.addEventListener('click', closeSuccessModal);
    elements.successModal?.addEventListener('click', (e) => {
        if (e.target === elements.successModal) {
            closeSuccessModal();
        }
    });

    // Закрытие по Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeSearch();
            closeProductModal();
            closeSuccessModal();
        }
    });
}

function goHome() {
    closeCategoryPage();
    closeCatalog();
    closeProfile();
    closeSearch();
}

// ===== ХЛЕБНЫЕ КРОШКИ =====
function updateBreadcrumbs() {
    const gameNames = {
        'brawlstars': 'Brawl Stars',
        'clashroyale': 'Clash Royale',
        'clashofclans': 'Clash of Clans'
    };

    if (currentGame) {
        elements.breadcrumbGame.textContent = gameNames[currentGame] || currentGame;
        elements.breadcrumbGame.style.display = 'flex';
    }

    if (currentSubcategory) {
        elements.breadcrumbCategory.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M21 10C21 17 12 23 12 23C12 23 3 17 3 10C3 7.61305 3.94821 5.32387 5.63604 3.63604C7.32387 1.94821 9.61305 1 12 1C14.3869 1 16.6761 1.94821 18.364 3.63604C20.0518 5.32387 21 7.61305 21 10Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            ${getCategoryName(currentSubcategory)}
        `;
        elements.breadcrumbCategory.style.display = 'flex';
        elements.breadcrumbCategorySeparator.style.display = 'inline';
        elements.breadcrumbGame.classList.remove('active');
        elements.breadcrumbCategory.classList.add('active');
    } else {
        elements.breadcrumbCategory.style.display = 'none';
        elements.breadcrumbCategorySeparator.style.display = 'none';
        elements.breadcrumbGame.classList.add('active');
    }
}

function handleBreadcrumbBack() {
    if (currentSubcategory) {
        closeCategoryPage();
    } else if (currentGame) {
        closeCatalog();
    } else {
        goHome();
    }
}

// ===== ПЕРЕКЛЮЧАТЕЛЬ ВИДА =====
function setViewMode(mode) {
    currentViewMode = mode;

    // Обновляем кнопки
    if (mode === 'list') {
        elements.viewList?.classList.add('active');
        elements.viewGrid?.classList.remove('active');
        elements.productsGrid?.classList.add('list-view');
    } else {
        elements.viewGrid?.classList.add('active');
        elements.viewList?.classList.remove('active');
        elements.productsGrid?.classList.remove('list-view');
    }
}

// ===== ПРОФИЛЬ =====

async function loadUserProfile() {
    if (!userId) {
        console.warn('User ID not available');
        return;
    }

    try {
        const response = await fetch(`${API_URL}/user/${userId}`);
        if (response.ok) {
            userProfile = await response.json();
            updateProfileUI();
        }
    } catch (error) {
        console.error('Error loading profile:', error);
    }
}

function updateProfileUI() {
    if (!userProfile) return;

    elements.userUID.textContent = `#${userProfile.uid}`;
    elements.userOrders.textContent = userProfile.orders_count;
}

async function openProfile() {
    hideAllPages();
    elements.profilePage.style.display = 'block';

    //Загружаем историю заказов
    await loadUserOrders();
}

function closeProfile() {
    elements.profilePage.style.display = 'none';
    elements.mainPage.style.display = 'block';
}

async function loadUserOrders() {
    const ordersList = document.getElementById('ordersList');
    if (!ordersList) return;

    ordersList.innerHTML = '<div class="orders-loading">Загрузка заказов...</div>';

    try {
        const response = await fetch(`${API_URL}/user/${userId}/orders`);
        if (response.ok) {
            const orders = await response.json();
            displayOrders(orders);
        } else {
            ordersList.innerHTML = '<div class="orders-empty">Не удалось загрузить заказы</div>';
        }
    } catch (error) {
        console.error('Error loading orders:', error);
        ordersList.innerHTML = '<div class="orders-empty">Ошибка загрузки</div>';
    }
}

function displayOrders(orders) {
    const ordersList = document.getElementById('ordersList');
    if (!ordersList) return;

    if (!orders || orders.length === 0) {
        ordersList.innerHTML = `
            <div class="orders-empty">
                <div style="font-size: 32px; margin-bottom: 8px;">📦</div>
                У вас пока нет заказов
            </div>
        `;
        return;
    }

    const statusLabels = {
        'completed': 'Выполнен',
        'pending': 'В обработке',
        'paid': 'Оплачен',
        'pending_payment': 'Ожидает оплаты',
        'cancelled': 'Отменён',
        'payment_failed': 'Ошибка оплаты'
    };

    const gameIcons = {
        'brawlstars': '⭐',
        'clashroyale': '👑',
        'clashofclans': '⚔️'
    };

    ordersList.innerHTML = orders.map(order => {
        const statusLabel = statusLabels[order.status] || order.status;
        const gameIcon = gameIcons[order.game] || '🎮';
        const date = new Date(order.created_at).toLocaleDateString('ru-RU', {
            day: 'numeric',
            month: 'short'
        });

        return `
            <div class="order-card">
                <div class="order-header">
                    <div class="order-product">${gameIcon} ${order.product_name}</div>
                    <span class="order-status ${order.status}">${statusLabel}</span>
                </div>
                <div class="order-details">
                    <div class="order-detail">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
                        </svg>
                        <span class="order-price">${formatPrice(order.amount)}₽</span>
                    </div>
                    ${order.pickup_code ? `
                        <div class="order-detail">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                                <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                            </svg>
                            <span class="order-code">${order.pickup_code}</span>
                        </div>
                    ` : ''}
                    <div class="order-detail order-date">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                            <line x1="16" y1="2" x2="16" y2="6"/>
                            <line x1="8" y1="2" x2="8" y2="6"/>
                            <line x1="3" y1="10" x2="21" y2="10"/>
                        </svg>
                        <span>${date}</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

function hideAllPages() {
    elements.mainPage.style.display = 'none';
    elements.catalogPage.style.display = 'none';
    elements.categoryPage.style.display = 'none';
    elements.profilePage.style.display = 'none';
}

// ===== КАТАЛОГ =====

async function loadAllProducts() {
    try {
        const response = await fetch(`${API_URL}/products`);
        if (response.ok) {
            allProducts = await response.json();
        }
    } catch (error) {
        console.error('Error loading products:', error);
    }
}

async function openCatalog(game) {
    currentGame = game;
    currentSubcategory = null;

    // Отображаем категории
    displayCategories(game);

    // Показываем skeleton loading
    showSkeletonLoading(elements.productsGrid, 4);
    elements.productCount.textContent = 'Загрузка...';

    // Загружаем все товары для игры
    try {
        const response = await fetch(`${API_URL}/products?game=${game}`);
        if (response.ok) {
            currentGameProducts = await response.json();
            // Фильтруем: в общем списке показываем ТОЛЬКО товары БЕЗ категории
            // Товары с категориями показываются только в своих категориях
            currentDisplayedProducts = currentGameProducts.filter(p => !p.subcategory || p.subcategory === '' || p.subcategory === 'all');
            displayProducts(currentDisplayedProducts, elements.productsGrid, elements.productCount);
        }
    } catch (error) {
        console.error('Error loading products:', error);
        elements.productsGrid.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">😕</div>
                <div class="empty-state-title">Ошибка загрузки</div>
                <div class="empty-state-text">Не удалось загрузить товары</div>
            </div>
        `;
    }

    hideAllPages();
    elements.catalogPage.style.display = 'block';
    updateBreadcrumbs();
}

function closeCatalog() {
    elements.catalogPage.style.display = 'none';
    elements.mainPage.style.display = 'block';
    currentGame = null;
}

function displayCategories(game) {
    // Категории синхронизированы с ботом (handlers/categories.py)
    const categories = {
        brawlstars: [
            { name: 'Акции', subcategory: 'akcii', emoji: '🔥' },
            { name: 'Гемы', subcategory: 'gems', emoji: '💎' }
        ],
        clashroyale: [
            { name: 'Акции', subcategory: 'akcii', emoji: '🔥' },
            { name: 'Гемы', subcategory: 'gems', emoji: '💎' },
            { name: 'Герои', subcategory: 'geroi', emoji: '🦸' },
            { name: 'Эволюции', subcategory: 'evolutions', emoji: '⚡' },
            { name: 'Эмодзи', subcategory: 'emoji', emoji: '😀' },
            { name: 'Этапные', subcategory: 'etapnye', emoji: '📈' },
            { name: 'Карты', subcategory: 'karty', emoji: '🃏' }
        ],
        clashofclans: [
            { name: 'Акции', subcategory: 'akcii', emoji: '🔥' },
            { name: 'Гемы', subcategory: 'gems', emoji: '💎' },
            { name: 'Оформление', subcategory: 'oformlenie', emoji: '🏠' }
        ]
    };

    const gameCategories = categories[game] || [];

    if (gameCategories.length === 0) {
        elements.categoriesGrid.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📦</div>
                <div class="empty-state-text">Категории скоро появятся</div>
            </div>
        `;
        return;
    }

    elements.categoriesGrid.innerHTML = gameCategories.map(cat => `
<div class="category-card ripple" onclick="openCategoryPage('${cat.subcategory}')">
    <div class="category-image-wrapper">
        <img class="category-image"
             src="/static/images/categories/${currentGame}/${cat.subcategory}.png"
             onerror="this.src='/static/images/categories/${currentGame}/main.png'"
             alt="${cat.name}">
    </div>
    <div class="category-footer">
        <span class="category-name">${cat.name}</span>
        <svg class="category-arrow" width="24" height="24" viewBox="0 0 24 24" fill="none">
            <path d="M9 18L15 12L9 6"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"/>
        </svg>
    </div>
</div>
`).join('');



    document.querySelectorAll('.category-card.ripple').forEach(el => {
        el.addEventListener('click', createRipple);
    });
}

// ===== СТРАНИЦА КАТЕГОРИИ =====

function openCategoryPage(subcategory) {
    currentSubcategory = subcategory;

    // Устанавливаем заголовок
    const categoryName = getCategoryName(subcategory);
    elements.categoryTitle.textContent = categoryName;

    // Обновляем breadcrumbs категории
    const gameNames = {
        'brawlstars': 'Brawl Stars',
        'clashroyale': 'Clash Royale',
        'clashofclans': 'Clash of Clans'
    };
    const categoryBreadcrumbGame = document.getElementById('categoryBreadcrumbGame');
    const categoryBreadcrumbName = document.getElementById('categoryBreadcrumbName');
    if (categoryBreadcrumbGame) categoryBreadcrumbGame.textContent = gameNames[currentGame] || currentGame;
    if (categoryBreadcrumbName) categoryBreadcrumbName.textContent = categoryName;

    // Показываем skeleton loading
    showSkeletonLoading(elements.categoryProductsGrid, 4);
    elements.categoryProductCount.textContent = 'Загрузка...';

    // Фильтруем товары по категории
    currentCategoryProducts = currentGameProducts.filter(p => p.subcategory === subcategory);

    // Отображаем товары
    displayCategoryProducts(currentCategoryProducts);

    // Показываем страницу категории
    hideAllPages();
    elements.categoryPage.style.display = 'block';
}

function closeCategoryPage() {
    elements.categoryPage.style.display = 'none';
    elements.catalogPage.style.display = 'block';
    currentSubcategory = null;
    updateBreadcrumbs();
}

function displayCategoryProducts(products) {
    elements.categoryProductCount.textContent = `${products.length} товаров`;

    if (products.length === 0) {
        elements.categoryProductsGrid.innerHTML = `
            <div class="empty-state" style="grid-column: 1 / -1;">
                <div class="empty-state-icon">📦</div>
                <div class="empty-state-title">Товаров пока нет</div>
                <div class="empty-state-text">Скоро здесь появятся новые товары</div>
            </div>
        `;
        return;
    }

    elements.categoryProductsGrid.innerHTML = products.map((product, index) => {
        let imageHtml;
        if (product.image_file_id) {
            imageHtml = `<img class="lazy-image" data-src="${API_URL}/product-image/${product.image_file_id}"
                src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E"
                onerror="this.parentElement.innerHTML='<span class=\\'placeholder-icon\\'>💎</span>'"
                alt="${product.name}">`;
        } else if (product.image_path) {
            imageHtml = `<img class="lazy-image" data-src="${product.image_path}"
                src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E"
                onerror="this.parentElement.innerHTML='<span class=\\'placeholder-icon\\'>💎</span>'"
                alt="${product.name}">`;
        } else {
            imageHtml = '<span class="placeholder-icon">💎</span>';
        }

        const badge = product.subcategory === 'akcii' ? '<span class="product-badge">Sale</span>' : '';

        const description = product.description || 'Нет описания';
        return `
            <div class="product-card ripple" data-game="${currentGame}" style="animation-delay: ${index * 0.05}s">
                <div class="product-image">
                    ${imageHtml}
                    <span class="product-price-badge">${formatPrice(product.price)}₽</span>
                    ${badge}
                </div>
                <div class="product-header" onclick="toggleProductDescription(this)">
                    <span class="product-name">${product.name}</span>
                    <svg class="product-expand-icon" width="20" height="20" viewBox="0 0 24 24" fill="none">
                        <path d="M6 9L12 15L18 9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </div>
                <div class="product-description-block" style="display: none;">
                    <p>${description}</p>
                </div>
                <div class="product-footer">
                    <span class="product-price">${formatPrice(product.price)} <span class="product-price-currency">₽</span></span>
                    <button class="product-buy-btn" onclick="event.stopPropagation(); buyProduct(${product.id})">Купить</button>
                </div>
            </div>
        `;
    }).join('');

    document.querySelectorAll('#categoryProductsGrid .product-card.ripple').forEach(el => {
        el.addEventListener('click', createRipple);
    });

    // Активируем lazy loading для изображений
    initLazyImages(elements.categoryProductsGrid);
}

function handleCategoryProductClick(index) {
    if (currentCategoryProducts[index]) {
        openProductModal(currentCategoryProducts[index]);
    }
}

function toggleProductDescription(headerElement) {
    const card = headerElement.closest('.product-card');
    const descBlock = card.querySelector('.product-description-block');
    const expandIcon = headerElement.querySelector('.product-expand-icon');

    if (descBlock.style.display === 'none') {
        descBlock.style.display = 'block';
        expandIcon.style.transform = 'rotate(180deg)';
        card.classList.add('expanded');
    } else {
        descBlock.style.display = 'none';
        expandIcon.style.transform = 'rotate(0deg)';
        card.classList.remove('expanded');
    }
}

// ===== ОСНОВНЫЕ ТОВАРЫ =====

function formatPrice(price) {
    return Math.floor(price).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

function displayProducts(products, gridElement, countElement) {
    countElement.textContent = `${products.length} товаров доступно`;

    if (products.length === 0) {
        gridElement.innerHTML = `
            <div class="empty-state" style="grid-column: 1 / -1;">
                <div class="empty-state-icon">📦</div>
                <div class="empty-state-title">Товаров пока нет</div>
                <div class="empty-state-text">Скоро здесь появятся новые товары</div>
            </div>
        `;
        return;
    }

    gridElement.innerHTML = products.map((product, index) => {
        let imageHtml;
        if (product.image_file_id) {
            imageHtml = `<img class="lazy-image" data-src="${API_URL}/product-image/${product.image_file_id}"
                src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E"
                onerror="this.parentElement.innerHTML='<span class=\\'placeholder-icon\\'>💎</span>'"
                alt="${product.name}">`;
        } else if (product.image_path) {
            imageHtml = `<img class="lazy-image" data-src="${product.image_path}"
                src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E"
                onerror="this.parentElement.innerHTML='<span class=\\'placeholder-icon\\'>💎</span>'"
                alt="${product.name}">`;
        } else {
            imageHtml = '<span class="placeholder-icon">💎</span>';
        }

        const badge = product.subcategory === 'akcii' ? '<span class="product-badge">Sale</span>' : '';

        return `
            <div class="product-card ripple" data-game="${currentGame}" onclick="handleProductClick(${index})" style="animation-delay: ${index * 0.05}s">
                <div class="product-image">
                    ${imageHtml}
                    <span class="product-price-badge">${formatPrice(product.price)}₽</span>
                    ${badge}
                    <span class="product-watermark">SUPERCELL SHOP</span>
                </div>
                <div class="product-header">
                    <span class="product-name">${product.name}</span>
                    <svg class="product-expand-icon" width="20" height="20" viewBox="0 0 24 24" fill="none">
                        <path d="M6 9L12 15L18 9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </div>
                <div class="product-footer">
                    <span class="product-price">${formatPrice(product.price)} <span class="product-price-currency">₽</span></span>
                    <button class="product-buy-btn" onclick="event.stopPropagation(); buyProduct(${product.id})">Купить</button>
                </div>
            </div>
        `;
    }).join('');

    gridElement.querySelectorAll('.product-card.ripple').forEach(el => {
        el.addEventListener('click', createRipple);
    });

    // Активируем lazy loading для изображений
    initLazyImages(gridElement);
}

function handleProductClick(index) {
    if (currentDisplayedProducts[index]) {
        openProductModal(currentDisplayedProducts[index]);
    }
}

// Функция для прямой покупки (если нужна быстрая покупка без шагов)
async function buyProduct(productId) {
    if (!userId) {
        showToast('Ошибка: не удалось определить пользователя', 'error');
        return;
    }

    // Открываем модальное окно для ввода данных
    const product = currentDisplayedProducts.find(p => p.id === productId) ||
                   currentCategoryProducts.find(p => p.id === productId) ||
                   allProducts.find(p => p.id === productId);

    if (product) {
        openProductModal(product);
    }
}

// ===== ПОИСК =====

let searchTimeout = null;
let searchResults = [];

function openSearch() {
    elements.searchOverlay.classList.add('active');
    elements.searchInput.focus();

    //Показываем подсказки
    showSearchSuggestions();
}

function closeSearch() {
    elements.searchOverlay.classList.remove('active');
    elements.searchInput.value = '';
    elements.searchResults.innerHTML = '';
    searchResults = [];
}

function showSearchSuggestions() {
    if (elements.searchInput.value.length > 0) return;

    elements.searchResults.innerHTML = `
        <div class="search-suggestions">
            <div class="search-suggestions-title">Популярные запросы</div>
            <div class="search-tags">
                <div class="search-tag" onclick="quickSearch('гемы')">💎 Гемы</div>
                <div class="search-tag" onclick="quickSearch('бравл пасс')">🎫 Бравл Пасс</div>
                <div class="search-tag" onclick="quickSearch('акции')">🎁 Акции</div>
                <div class="search-tag" onclick="quickSearch('clash royale')">👑 Clash Royale</div>
            </div>
        </div>
        <div class="search-suggestions" style="margin-top: 20px;">
            <div class="search-suggestions-title">Игры</div>
            <div class="search-tags">
                <div class="search-tag" onclick="openCatalog('brawlstars'); closeSearch();">⭐ Brawl Stars</div>
                <div class="search-tag" onclick="openCatalog('clashroyale'); closeSearch();">👑 Clash Royale</div>
                <div class="search-tag" onclick="openCatalog('clashofclans'); closeSearch();">⚔️ Clash of Clans</div>
            </div>
        </div>
    `;
}

function quickSearch(query) {
    elements.searchInput.value = query;
    handleSearch({ target: elements.searchInput });
}

async function handleSearch(e) {
    const query = e.target.value.trim();

    //Очищаем предыдущий таймаут
    if (searchTimeout) {
        clearTimeout(searchTimeout);
    }

    if (query.length < 2) {
        showSearchSuggestions();
        return;
    }

    //Debounce - ждём 300мс после ввода
    searchTimeout = setTimeout(async () => {
        elements.searchResults.innerHTML = '<div class="orders-loading">Поиск...</div>';

        try {
            const response = await fetch(`${API_URL}/search?q=${encodeURIComponent(query)}`);
            if (response.ok) {
                searchResults = await response.json();
                displaySearchResults(searchResults, query);
            }
        } catch (error) {
            console.error('Search error:', error);
            //Fallback на локальный поиск
            const filtered = allProducts.filter(p =>
                p.name.toLowerCase().includes(query.toLowerCase()) ||
                (p.description && p.description.toLowerCase().includes(query.toLowerCase()))
            );
            searchResults = filtered;
            displaySearchResults(filtered, query);
        }
    }, 300);
}

function highlightText(text, query) {
    if (!text || !query) return text || '';
    const regex = new RegExp(`(${query})`, 'gi');
    return text.replace(regex, '<span class="search-highlight">$1</span>');
}

function displaySearchResults(products, query = '') {
    if (products.length === 0) {
        elements.searchResults.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🔍</div>
                <div class="empty-state-title">Ничего не найдено</div>
                <div class="empty-state-text">Попробуйте другой запрос</div>
            </div>
            <div class="search-suggestions" style="margin-top: 20px;">
                <div class="search-suggestions-title">Попробуйте</div>
                <div class="search-tags">
                    <div class="search-tag" onclick="quickSearch('гемы')">💎 Гемы</div>
                    <div class="search-tag" onclick="quickSearch('пасс')">🎫 Пасс</div>
                </div>
            </div>
        `;
        return;
    }

    const gameIcons = {
        'brawlstars': '⭐',
        'clashroyale': '👑',
        'clashofclans': '⚔️'
    };

    elements.searchResults.innerHTML = `
        <div style="padding: 0 4px 8px; color: var(--text-secondary); font-size: 13px;">
            Найдено: ${products.length}
        </div>
        ${products.map((product, index) => {
            let imageUrl = '/static/images/main.png';
            if (product.image_file_id) {
                imageUrl = `${API_URL}/product-image/${product.image_file_id}`;
            } else if (product.image_path) {
                imageUrl = product.image_path;
            }
            const gameIcon = gameIcons[product.game] || '🎮';

            return `
            <div class="search-item" onclick="openProductFromSearch(${index})">
                <div class="search-item-image">
                    <img src="${imageUrl}" onerror="this.src='/static/images/main.png'" alt="${product.name}">
                </div>
                <div class="search-item-content">
                    <div class="search-item-header">
                        <span>${gameIcon}</span>
                        <span style="font-weight: 600;">${highlightText(product.name, query)}</span>
                    </div>
                    <div class="search-item-desc">${highlightText(product.description || '', query)}</div>
                    <div class="search-item-footer">
                        <span class="search-item-price">${formatPrice(product.price)}₽</span>
                        <span class="search-item-category">${getCategoryName(product.subcategory)}</span>
                    </div>
                </div>
            </div>
        `}).join('')}
    `;
}

async function openProductFromSearch(index) {
    const product = searchResults[index];
    if (!product) return;

    closeSearch();

    // Сохраняем ID товара для выделения
    const highlightProductId = product.id;

    // Открываем каталог нужной игры
    await openCatalog(product.game);

    // Определяем, нужно ли открыть категорию или товар в общем списке
    const specialCategories = ['akcii', 'gems', 'bp'];

    if (specialCategories.includes(product.subcategory)) {
        // Открываем страницу категории
        openCategoryPage(product.subcategory);

        // Ждём рендеринг и выделяем товар
        setTimeout(() => {
            highlightAndScrollToProduct(highlightProductId, elements.categoryProductsGrid);
        }, 100);
    } else {
        // Товар в общем списке каталога
        setTimeout(() => {
            highlightAndScrollToProduct(highlightProductId, elements.productsGrid);
        }, 100);
    }
}

function highlightAndScrollToProduct(productId, gridElement) {
    // Находим карточку товара
    const productCards = gridElement.querySelectorAll('.product-card');

    productCards.forEach((card, index) => {
        // Получаем ID товара из onclick или data-атрибута
        const products = gridElement === elements.categoryProductsGrid
            ? currentCategoryProducts
            : currentDisplayedProducts;

        if (products[index] && products[index].id === productId) {
            // Добавляем класс выделения
            card.classList.add('highlighted');

            // Прокручиваем к товару
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });

            // Убираем выделение через 3 секунды
            setTimeout(() => {
                card.classList.remove('highlighted');
            }, 3000);
        }
    });
}

function selectSearchResult(productId, game) {
    closeSearch();
    openCatalog(game);
}

// Запуск приложения
init();

// Устанавливаем цвета темы (только если запущено в Telegram)
if (tg.setHeaderColor) {
    tg.setHeaderColor('#1a1f2e');
    tg.setBackgroundColor('#0f1419');
}
