<?php
/** Удобства Adminer для проекта «Охрана труда».
 *
 * - таблицы и колонки подписаны по-русски (берутся из комментариев в БД, миграция 0006);
 * - вместо UUID связанной записи показывается её название (заказчик, сотрудник, курс…),
 *   а в форме редактирования связь выбирается из списка по названию;
 * - хеши паролей и токенов скрыты, да/нет вместо t/f, роли и статусы по-русски, длинные id сокращены;
 * - служебная таблица alembic_version скрыта из меню;
 * - форма входа заполнена заранее — нужно ввести только пароль.
 */
class AdminerOhsFriendly {
	const LABEL_COLUMNS = array("name", "full_name", "title");
	const SECRET_COLUMNS = array("password_hash", "token_hash");
	const MAX_OPTIONS = 5000;
	const HIDDEN_TABLES = array("alembic_version"); // служебные, в меню не показываем
	const VALUES = array(
		"role" => array("superadmin" => "Главный администратор", "center_admin" => "Директор",
			"org_admin" => "Заказчик", "employee" => "Подчинённый"),
		"status" => array("active" => "Активен", "inactive" => "Деактивирован", "blocked" => "Заблокирован",
			"assigned" => "Назначен", "in_progress" => "В процессе", "passed" => "Пройден"),
		"kind" => array("document" => "Документ", "video" => "Видео"),
	);

	private $foreign = array(); // [таблица] => column_foreign_keys()
	private $labelColumn = array(); // [таблица] => колонка с названием или false
	private $labels = array(); // [таблица] => [id => название] или false, если записей слишком много

	function name() {
		return "<a href='" . h(ME) . "' id='h1'>База данных <small>Охрана труда</small></a>";
	}

	function loginForm() {
		echo "<p class='ohs-login-hint'>Сервер, система, пользователь и база уже заполнены. "
			. "Введите пароль — значение <b>POSTGRES_PASSWORD</b> из файла <b>.env</b> в папке проекта.</p>\n";
		return null; // дальше рисуется обычная форма
	}

	function loginFormField($name, $heading, $value) {
		if ($name == "driver") {
			$value = str_replace(" selected", "", $value);
			$value = str_replace('<option value="pgsql">', '<option value="pgsql" selected>', $value);
		} elseif ($name == "server") {
			$value = str_replace('name="auth[server]" value=""', 'name="auth[server]" value="' . h(getenv("ADMINER_DEFAULT_SERVER") ?: "db") . '"', $value);
		} elseif ($name == "username" && getenv("ADMINER_DEFAULT_USER")) {
			$value = str_replace('name="auth[username]" id="username" value=""', 'name="auth[username]" id="username" value="' . h(getenv("ADMINER_DEFAULT_USER")) . '"', $value);
		} elseif ($name == "db" && getenv("ADMINER_DEFAULT_DB")) {
			$value = str_replace('name="auth[db]" value=""', 'name="auth[db]" value="' . h(getenv("ADMINER_DEFAULT_DB")) . '"', $value);
		}
		return $heading . $value;
	}

	function tableName($tableStatus) {
		if (in_array($tableStatus["Name"], self::HIDDEN_TABLES)) {
			return "";
		}
		if (($tableStatus["Comment"] ?? "") == "") {
			return null;
		}
		return h($tableStatus["Comment"]) . " <span class='tn'>(" . h($tableStatus["Name"]) . ")</span>";
	}

	/** Меню таблиц: русское название открывает записи, значок ⚙ — структуру. По алфавиту. */
	function tablesPrint($tables) {
		$items = array();
		foreach ($tables as $table => $status) {
			if (!in_array($table, self::HIDDEN_TABLES)) {
				$items[$table] = (($status["Comment"] ?? "") != "" ? $status["Comment"] : $table);
			}
		}
		asort($items);
		$current = array($_GET["select"] ?? null, $_GET["edit"] ?? null, $_GET["table"] ?? null,
			$_GET["create"] ?? null, $_GET["indexes"] ?? null, $_GET["foreign"] ?? null);
		echo "<ul id='tables'><li class='ohs-nav-title'>Таблицы</li>\n";
		foreach ($items as $table => $label) {
			$url = h(ME) . "%s=" . urlencode($table);
			echo "<li" . (in_array($table, $current, true) ? " class='active'" : "") . ">"
				. "<a class='ohs-open' href='" . sprintf($url, "select") . "' title='Открыть записи'>"
				. "<b>" . h($label) . "</b><small>" . h($table) . "</small></a>"
				. "<a class='ohs-struct' href='" . sprintf($url, "table") . "' title='Структура таблицы'>⚙</a></li>\n";
		}
		echo "</ul>\n";
		return true; // стандартный список не выводим
	}

	function fieldName($field, $order = 0) {
		if (($field["comment"] ?? "") == "") {
			return null;
		}
		return "<span title='" . h($field["field"] . " · " . $field["full_type"]) . "'>" . h($field["comment"]) . "</span>";
	}

	function selectVal($val, $link, $field, $original) {
		if (!isset($_GET["select"])) {
			return null; // результаты SQL-запросов показываем как есть
		}
		if (in_array($field["field"], self::SECRET_COLUMNS)) {
			return "<span class='ohs-hidden'>скрыто</span>";
		}
		if ($original === null) {
			return null;
		}
		$text = null;
		$target = $this->target($_GET["select"], $field["field"]);
		$label = ($target ? $this->label($target, $original) : null);
		if ($label !== null) {
			$text = "<span class='ohs-ref' title='" . h($original) . "'>" . h($label) . "</span>";
		} elseif (isset(self::VALUES[$field["field"]][$original])) {
			$text = "<span title='" . h($original) . "'>" . h(self::VALUES[$field["field"]][$original]) . "</span>";
		} elseif ($field["type"] == "uuid") {
			$text = "<span class='ohs-id' title='" . h($original) . "'>" . h(substr($original, 0, 8)) . "…</span>";
		} elseif ($field["type"] == "boolean") {
			$yes = preg_match('~^(1|t|true)$~i', $original);
			$text = "<span class='" . ($yes ? "ohs-yes'>да" : "ohs-no'>нет") . "</span>";
		}
		if ($text === null) {
			return null;
		}
		// быстрое редактирование ячейки (Ctrl+клик) берёт значение из alt первого элемента —
		// подкладываем настоящее значение, иначе в базу ушла бы подпись
		$original = "<img alt='" . h($original) . "' hidden>";
		return $original . ($link ? "<a href='" . h($link) . "'>$text</a>" : $text);
	}

	function editInput($table, $field, $attrs, $value) {
		$target = $this->target($table, $field["field"]);
		$options = ($target ? $this->options($target) : null);
		if (!$options) {
			return null;
		}
		$options = ($field["null"] ? array("" => "— не выбрано —") : array()) + $options;
		return "<select$attrs>" . optionlist($options, $value, true) . "</select>";
	}

	function processInput($field, $value, $function = "") {
		// пустой выбор в списке связанной записи = NULL, а не пустая строка
		if ($function == "" && $value === "" && $field["null"] && isset($_GET["edit"])
			&& $this->target($_GET["edit"], $field["field"])) {
			return "NULL";
		}
		return null;
	}

	/** Таблица, на которую ссылается колонка (только если у неё есть колонка с названием). */
	private function target($table, $column) {
		if (!isset($this->foreign[$table])) {
			$this->foreign[$table] = column_foreign_keys($table);
		}
		foreach ((array) ($this->foreign[$table][$column] ?? array()) as $fk) {
			if (count($fk["source"]) == 1 && $this->labelColumn($fk["table"])) {
				return array($fk["table"], $fk["target"][0]);
			}
		}
		return null;
	}

	private function labelColumn($table) {
		if (!isset($this->labelColumn[$table])) {
			$fields = fields($table);
			$this->labelColumn[$table] = false;
			foreach (self::LABEL_COLUMNS as $name) {
				if (isset($fields[$name])) {
					$this->labelColumn[$table] = $name;
					break;
				}
			}
		}
		return $this->labelColumn[$table];
	}

	private function options($target) {
		list($table, $id) = $target;
		if (!isset($this->labels[$table])) {
			$name = idf_escape($this->labelColumn($table));
			$rows = get_key_vals("SELECT " . idf_escape($id) . ", $name FROM " . table($table)
				. " ORDER BY $name LIMIT " . (self::MAX_OPTIONS + 1));
			$this->labels[$table] = (count($rows) > self::MAX_OPTIONS ? false : $rows);
		}
		return $this->labels[$table] ?: null;
	}

	private function label($target, $id) {
		$options = $this->options($target);
		return ($options && isset($options[$id]) ? $options[$id] : null);
	}
}

return new AdminerOhsFriendly;
